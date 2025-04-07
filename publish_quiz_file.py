#!/usr/bin/env python
"""
CLI script for publishing a quiz from a JSON file to the InceptStore API.
Usage: python publish_quiz_file.py <quiz_file.json> [--course-name "Course Name"] [--module-name "Module Name"] [--item-name "Item Name"] [--xp 25]
"""

import asyncio
import json
import argparse
import os
import sys
from publish_questions import PublishQuestions

async def publish_quiz_from_file(file_path, course_name, module_name, item_name, xp_value):
    """
    Publish a quiz from a JSON file
    
    Args:
        file_path: Path to the JSON file containing the quiz
        course_name: Name of the course to publish to
        module_name: Name of the module to publish to
        item_name: Name of the item to publish
        xp_value: XP value for the quiz
    
    Returns:
        True if the publishing was successful, False otherwise
    """
    print(f"\n=== Publishing Quiz from {file_path} ===\n")
    
    # Validate file path
    if not os.path.exists(file_path):
        print(f"Error: File {file_path} does not exist")
        return False
    
    # Read the quiz file
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            quiz = json.load(f)
        print(f"Successfully loaded quiz file: {file_path}")
        print(f"Quiz contains {len(quiz.get('questions', []))} questions")
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in file: {str(e)}")
        return False
    except Exception as e:
        print(f"Error reading file: {str(e)}")
        return False
    
    # Initialize the publisher
    publisher = PublishQuestions()
    print("Publisher initialized")
    
    # Create the course details
    course_details = {
        "course": {"title": course_name},
        "module": {"name": module_name},
        "items": [
            {
                "name": item_name,
                "contentType": "quiz",
                "xp": xp_value
            }
        ]
    }
    print(f"Course details prepared for: {course_name}")
    
    # Format the quiz for the API
    print("\nFormatting quiz for API...")
    payload = publisher.format_quiz_for_api(quiz, course_details)
    
    # Publish the quiz to the API
    print("\nPublishing quiz to API...")
    try:
        api_response = await publisher.publish_quiz_to_api(payload)
        
        print("\nAPI Response received:")
        print(json.dumps(api_response, indent=2))
        
        # Check for success
        if publisher.check_publish_success(api_response):
            print("\nPublishing completed successfully!")
            print(f"Course ID: {api_response['course_id']}")
            print(f"Module ID: {api_response['module_id']}")
            print(f"Item ID: {api_response['item_id']}")
            if "view_url" in api_response:
                print(f"View URL: {api_response['view_url']}")
            return True
        else:
            print("\nPublishing may have failed - no course_id in response")
            return False
    
    except Exception as e:
        print(f"\nError during publishing: {str(e)}")
        return False

def main():
    """
    Parse command line arguments and publish the quiz
    """
    parser = argparse.ArgumentParser(description='Publish a quiz from a JSON file to the InceptStore API')
    parser.add_argument('quiz_file', help='Path to the JSON file containing the quiz')
    parser.add_argument('--course-name', default='Test Course', help='Name of the course to publish to')
    parser.add_argument('--module-name', default='Test Module', help='Name of the module to publish to')
    parser.add_argument('--item-name', default='JSON Quiz', help='Name of the item to publish')
    parser.add_argument('--xp', type=int, default=25, help='XP value for the quiz')
    
    args = parser.parse_args()
    
    success = asyncio.run(publish_quiz_from_file(
        args.quiz_file,
        args.course_name,
        args.module_name,
        args.item_name,
        args.xp
    ))
    
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main() 