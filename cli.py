#!/usr/bin/env python3
"""
Command-line interface for the Quiz Generator.
"""

import os
import sys
import json
import argparse
import asyncio
import logging
from typing import Dict, Any, Optional, List
import time

# Import centralized logging
from logging_config import logger, configure_logging

# Import centralized configuration
from config import config

# Import the QuizGenerator
try:
    from main import QuizGenerator
except ImportError:
    logger.error("Could not import QuizGenerator from main.py")
    sys.exit(1)

# Import the PublishQuestions class
try:
    from publish_questions import PublishQuestions
except ImportError:
    logger.error("Could not import PublishQuestions from publish_questions.py")
    logger.warning("Publishing features will not be available")
    PublishQuestions = None

def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Generate educational quizzes using Claude.")

    # List operations (should not require lesson/standard)
    list_group = parser.add_argument_group("List operations")
    list_group.add_argument("--list-lessons", action="store_true", help="List available lessons")
    list_group.add_argument("--list-standards", action="store_true", help="List available standards")

    # Quiz generation options
    quiz_group = parser.add_argument_group("Quiz generation")
    lesson_standard_group = quiz_group.add_mutually_exclusive_group()
    lesson_standard_group.add_argument("--lesson", type=str, help="Name of the lesson to create a quiz for")
    lesson_standard_group.add_argument("--standard", type=str, help="Specific standard to quiz")

    # Optional arguments
    parser.add_argument("--difficulty", type=int, choices=[1, 2, 3], default=1,
                        help="Quiz difficulty level: 1 (easy), 2 (medium), or 3 (hard)")
    parser.add_argument("--num-questions", type=int, default=6,
                        help="Number of questions to generate (6-12)")
    parser.add_argument("--output-file", type=str, help="Path to save the output JSON")
    parser.add_argument("--api-key", type=str, help="Anthropic API key (overrides environment variable)")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    
    # Publishing options
    publish_group = parser.add_argument_group("Publishing options")
    publish_group.add_argument("--publish", action="store_true", help="Publish the quiz to the database after generation")
    publish_group.add_argument("--publish-only", type=str, help="Publish an existing quiz JSON file")
    
    # Publishing mode options (mutually exclusive)
    publish_mode = publish_group.add_mutually_exclusive_group()
    publish_mode.add_argument("--new-course", action="store_true", 
                             help="Create a new course when publishing")
    publish_mode.add_argument("--existing-course", type=str, metavar="COURSE_ID",
                             help="Add a new module to an existing course with the specified ID")
    publish_mode.add_argument("--update-module", type=str, metavar="COURSE_ID:MODULE_ID",
                             help="Update an existing module in an existing course. Format: COURSE_ID:MODULE_ID")

    # Quiz item details
    publish_group.add_argument("--module-name", type=str, help="Module name for publishing (for new modules)")
    publish_group.add_argument("--item-name", type=str, help="Quiz item name for publishing")
    publish_group.add_argument("--xp-value", type=int, help="XP value for completing the quiz")

    args = parser.parse_args()
    
    # Validate arguments - require lesson or standard if not listing or publishing only
    if not (args.list_lessons or args.list_standards or args.publish_only) and not (args.lesson or args.standard):
        parser.error("One of --lesson or --standard is required when not using list operations or --publish-only")
    
    # Check if publishing is available when requested    
    if (args.publish or args.publish_only) and PublishQuestions is None:
        parser.error("Publishing features are not available. Make sure publish_questions.py is in the same directory.")
    
    # Validate the update-module format if provided
    if args.update_module and ":" not in args.update_module:
        parser.error("--update-module requires the format COURSE_ID:MODULE_ID")
        
    return args


def save_output(quiz_data: Dict[str, Any], output_file: Optional[str] = None) -> str:
    """Save quiz data to a file."""
    if not output_file:
        # Generate a default filename based on the quiz content
        lesson_or_standard = quiz_data.get("metadata", {}).get("lesson_name") or quiz_data.get("metadata", {}).get("standard_id")
        lesson_or_standard = lesson_or_standard.replace(" ", "_").lower() if lesson_or_standard else "quiz" 
        difficulty = quiz_data.get("metadata", {}).get("difficulty", "1")
        timestamp = quiz_data.get("metadata", {}).get("timestamp", "").replace(":", "-").replace(" ", "_")

        output_file = f"quiz_{lesson_or_standard}_diff{difficulty}_{timestamp}.json"

    try:
        # Create directory if it doesn't exist
        output_dir = os.path.dirname(output_file)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)
            logger.info(f"Created directory: {output_dir}")

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(quiz_data, f, indent=2)
        
        logger.info(f"Quiz data saved to: {output_file}")
        return output_file
    except PermissionError:
        error_msg = f"Permission denied when writing to {output_file}"
        logger.error(error_msg)
        
        # Try to save to a fallback location
        fallback_file = f"quiz_fallback_{int(time.time())}.json"
        logger.info(f"Attempting to save to fallback location: {fallback_file}")
        
        try:
            with open(fallback_file, "w", encoding="utf-8") as f:
                json.dump(quiz_data, f, indent=2)
            logger.info(f"Quiz data saved to fallback location: {fallback_file}")
            return fallback_file
        except Exception as e:
            logger.error(f"Failed to save to fallback location: {str(e)}")
            raise
    except Exception as e:
        error_msg = f"Error saving quiz data: {str(e)}"
        logger.error(error_msg)
        raise

def list_available_lessons(generator: QuizGenerator):
    """List all available lessons."""
    print("\nAvailable Lessons:")
    print("=================")

    if not generator.standards_by_lesson:
        print("No lessons found. Make sure the lesson data is loaded correctly.")
        return

    for i, lesson_name in enumerate(sorted(generator.standards_by_lesson.keys()), 1):
        standard = generator.standards_by_lesson.get(lesson_name, "")
        print(f"{i}. {lesson_name} - Standard: {standard}")

def list_available_standards(generator: QuizGenerator):
    """List all available standards."""
    print("\nAvailable Standards:")
    print("===================")

    if not generator.lessons_by_standard:
        print("No standards found. Make sure the standard data is loaded correctly.")
        return

    for i, standard in enumerate(sorted(generator.lessons_by_standard.keys()), 1):
        lessons = generator.lessons_by_standard.get(standard, [])
        lesson_names = ", ".join(lessons) if lessons else "No lessons"
        print(f"{i}. {standard} - Lessons: {lesson_names}")

async def get_course_details_from_args(args) -> Dict[str, Any]:
    """
    Create course details structure from command-line arguments.
    
    Args:
        args: Command-line arguments
        
    Returns:
        Course details dictionary for API
    """
    # Prepare course details based on the arguments provided
    
    if args.update_module:
        # Updating an existing module in an existing course
        try:
            course_id, module_id = args.update_module.split(":", 1)
        except ValueError:
            # This should be caught by the argument parser, but just in case
            raise ValueError("--update-module requires the format COURSE_ID:MODULE_ID")
        
        course_details = {
            "items": [
                {
                    "name": args.item_name or "Updated Quiz",
                    "contentType": "quiz",
                    "xp": args.xp_value or 10
                }
            ],
            "course_id": course_id,
            "module_id": module_id
        }
    elif args.existing_course:
        # Creating new module in existing course
        course_details = {
            "module": {"name": args.module_name or "New Module"},
            "items": [
                {
                    "name": args.item_name or "Quiz",
                    "contentType": "quiz",
                    "xp": args.xp_value or 10
                }
            ],
            "course_id": args.existing_course
        }
    else:
        # Creating a new course
        course_details = {
            "course": {"title": args.item_name or "New Course"},
            "module": {"name": args.module_name or "New Module"},
            "items": [
                {
                    "name": args.item_name or "Quiz",
                    "contentType": "quiz",
                    "xp": args.xp_value or 10
                }
            ]
        }
    
    return course_details

async def publish_quiz(quiz_data: Dict[str, Any], args) -> Dict[str, Any]:
    """
    Publish a quiz to the database.
    
    Args:
        quiz_data: The quiz data to publish
        args: Command-line arguments
        
    Returns:
        Dictionary with the results of the operation
    """
    if PublishQuestions is None:
        logger.error("PublishQuestions module is not available")
        return {
            "success": False,
            "messages": ["Publishing module is not available"]
        }
    
    try:
        publisher = PublishQuestions()
        
        # Check if we have explicit publish mode from arguments
        if args.new_course or args.existing_course or args.update_module or args.module_name or args.item_name or args.xp_value:
            # Use non-interactive mode with command-line arguments
            result = {
                "success": False,
                "actions": [],
                "messages": []
            }
            
            # Save the quiz to a file
            saved_file = await publisher.save_quiz_to_file(quiz_data)
            result["actions"].append("saved")
            result["saved_file"] = saved_file
            result["messages"].append(f"Quiz saved to {saved_file}")
            
            # Get course details from command-line arguments
            course_details = await get_course_details_from_args(args)
            
            # Format the quiz for the API
            payload = publisher.format_quiz_for_api(quiz_data, course_details)
            
            # Publish to the API
            api_response = await publisher.publish_to_api(payload)
            
            # Set appropriate action and message based on mode
            if args.update_module:
                course_id, module_id = args.update_module.split(":", 1)
                result["actions"].append("updated_existing_module")
                result["messages"].append(f"Quiz successfully updated in existing module (Course ID: {course_id}, Module ID: {module_id}).")
            elif args.existing_course:
                result["actions"].append("published_to_existing_course")
                result["messages"].append(f"Quiz successfully published to existing course (ID: {args.existing_course}) as a new module.")
            else:
                result["actions"].append("published_new_course")
                result["messages"].append("Quiz successfully published as a new course.")
                
            result["api_response"] = api_response
            result["success"] = True
            
            return result
        else:
            # Use interactive mode
            return await publisher.process_quiz(quiz_data)
    
    except Exception as e:
        logger.error(f"Error publishing quiz: {str(e)}")
        return {
            "success": False,
            "messages": [f"Error: {str(e)}"]
        }

async def publish_existing_quiz(file_path: str, args) -> Dict[str, Any]:
    """
    Publish an existing quiz from a JSON file.
    
    Args:
        file_path: Path to the quiz JSON file
        args: Command-line arguments
        
    Returns:
        Dictionary with the results of the operation
    """
    try:
        # Load the quiz data from the file
        with open(file_path, "r", encoding="utf-8") as f:
            quiz_data = json.load(f)
        
        logger.info(f"Loaded quiz data from {file_path}")
        
        # Publish the quiz
        return await publish_quiz(quiz_data, args)
    
    except FileNotFoundError:
        logger.error(f"Quiz file not found: {file_path}")
        return {
            "success": False,
            "messages": [f"Quiz file not found: {file_path}"]
        }
    except json.JSONDecodeError:
        logger.error(f"Invalid JSON in quiz file: {file_path}")
        return {
            "success": False,
            "messages": [f"Invalid JSON in quiz file: {file_path}"]
        }
    except Exception as e:
        logger.error(f"Error publishing existing quiz: {str(e)}")
        return {
            "success": False,
            "messages": [f"Error: {str(e)}"]
        }

async def main():
    """Main entry point for the CLI."""
    args = parse_args()

    # Set log level based on verbosity
    if args.verbose:
        configure_logging(logging.DEBUG)

    # Set API key if provided
    if args.api_key:
        os.environ["ANTHROPIC_API_KEY"] = args.api_key
        logger.info("Using Anthropic API key from command line")

    # Check if we're just publishing an existing quiz
    if args.publish_only:
        logger.info(f"Publishing existing quiz: {args.publish_only}")
        result = await publish_existing_quiz(args.publish_only, args)
        
        if result["success"]:
            logger.info("Quiz published successfully")
            for message in result["messages"]:
                print(message)
        else:
            logger.error("Failed to publish quiz")
            for message in result["messages"]:
                print(f"Error: {message}")
            sys.exit(1)
        
        return

    # Create the quiz generator
    try:
        generator = QuizGenerator()
    except FileNotFoundError as e:
        logger.error(f"Failed to initialize QuizGenerator: Required file not found: {str(e)}")
        sys.exit(1)
    except ValueError as e:
        logger.error(f"Failed to initialize QuizGenerator: Invalid data: {str(e)}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to initialize QuizGenerator: {str(e)}")
        sys.exit(1)

    # Handle listing commands
    if args.list_lessons:
        list_available_lessons(generator)
        return

    if args.list_standards:
        list_available_standards(generator)
        return

    # Validate args
    if args.num_questions < 1 or args.num_questions > 12:
        logger.error("Number of questions must be between 1 and 12")
        sys.exit(1)

    # Generate the quiz
    try:
        logger.info(f"Generating quiz with: " +
                   f"{'Lesson: ' + args.lesson if args.lesson else 'Standard: ' + args.standard}, " +
                   f"Difficulty: {args.difficulty}, " +
                   f"Questions: {args.num_questions}")

        if args.lesson:
            # Check if lesson exists
            if args.lesson not in generator.standards_by_lesson:
                available_lessons = list(generator.standards_by_lesson.keys())
                logger.error(f"Lesson '{args.lesson}' not found")
                if available_lessons:
                    logger.info(f"Available lessons include: {', '.join(available_lessons[:5])}" +
                               (", and more..." if len(available_lessons) > 5 else ""))
                    logger.info("Use --list-lessons to see all available lessons")
                sys.exit(1)

            # Use await to properly handle the coroutine
            quiz = await generator.generate_quiz(
                lesson_name=args.lesson,
                difficulty=args.difficulty,
                num_questions=args.num_questions
            )
        else:
            # Check if standard exists
            if args.standard not in generator.lessons_by_standard:
                available_standards = list(generator.lessons_by_standard.keys())
                logger.error(f"Standard '{args.standard}' not found")
                if available_standards:
                    logger.info(f"Available standards include: {', '.join(available_standards[:5])}" +
                               (", and more..." if len(available_standards) > 5 else ""))
                    logger.info("Use --list-standards to see all available standards")
                sys.exit(1)

            # Use await to properly handle the coroutine
            quiz = await generator.generate_quiz(
                standard_id=args.standard,
                difficulty=args.difficulty,
                num_questions=args.num_questions
            )

        # Check if quiz was generated successfully
        error_message = quiz.get("metadata", {}).get("error")
        if error_message:
            logger.warning(f"Quiz generated with warnings: {error_message}")
        
        # Print a summary
        passage_title = quiz.get("passage", {}).get("title", "Unknown title")
        passage_author = quiz.get("passage", {}).get("author", "Unknown author")
        num_questions_generated = quiz.get("metadata", {}).get("num_questions_generated", 0)
        
        print(f"\nGenerated quiz on: {passage_title} by {passage_author}")
        print(f"Total questions: {num_questions_generated}")
        
        # Check if we should publish the quiz
        if args.publish:
            logger.info("Publishing quiz to database")
            publish_result = await publish_quiz(quiz, args)
            
            if publish_result["success"]:
                logger.info("Quiz published successfully")
                for message in publish_result["messages"]:
                    print(message)
                
                # If the quiz was saved during publishing, get the filename
                if "saved_file" in publish_result:
                    output_file = publish_result["saved_file"]
                    print(f"Output saved to: {output_file}")
            else:
                logger.error("Failed to publish quiz")
                for message in publish_result["messages"]:
                    print(f"Error: {message}")
                
                # Still save the output even if publishing failed
                output_file = save_output(quiz, args.output_file)
                print(f"Output saved to: {output_file}")
        else:
            # Just save the output without publishing
            output_file = save_output(quiz, args.output_file)
            print(f"Output saved to: {output_file}")

    except KeyboardInterrupt:
        logger.info("Quiz generation cancelled by user")
        sys.exit(130)  # Standard exit code for SIGINT
    except Exception as e:
        logger.error(f"Failed to generate quiz: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main()) 