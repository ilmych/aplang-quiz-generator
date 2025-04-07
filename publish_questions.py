"""
Module for publishing quizzes to the API.
This module provides functionality to publish quizzes to a remote database
through an API endpoint.
"""

import json
import requests
import asyncio
from typing import Dict, List, Any, Optional
import os
import pathlib
import aiohttp
import logging

# Import centralized logging configuration
from logging_config import logger

# Import centralized configuration
from config import config

# Import utility functions
from utils import with_retry

class PublishQuestions:
    """
    Class responsible for publishing quizzes to a remote database through an API.
    """
    
    # API endpoint for publishing quizzes - fetched from config
    PUBLISH_ENDPOINT = config.INCEPTSTORE_API_URL
    
    def __init__(self):
        """
        Initialize the PublishQuestions class.
        """
        # No API key required for InceptStore
        self.endpoint = self.PUBLISH_ENDPOINT
        self.timeout = config.API_TIMEOUT
        logger.info(f"Publishing endpoint initialized: {self.endpoint}")
    
    async def ask_user(self, question: str) -> str:
        """
        Asks the user a question and returns their response.
        
        Args:
            question: The question to ask the user
            
        Returns:
            The user's response
        """
        print(f"\n{question}")
        return input("> ").strip().lower()
    
    def format_quiz_for_api(self, quiz: Dict[str, Any], course_details: Dict[str, Any]) -> Dict[str, Any]:
        """
        Formats the quiz for the API payload.
        
        Args:
            quiz: The quiz to format
            course_details: The course details
            
        Returns:
            The formatted API payload
        """
        # Extract the questions and passage from the quiz
        questions = quiz.get("questions", [])
        passage = quiz.get("passage", {})
        passage_text = passage.get("text", "")
        
        # Format each question for the API
        formatted_questions = []
        for question in questions:
            # Extract the question details
            question_text = question.get("question", "")
            correct_answer = question.get("correct_answer", "")
            distractor1 = question.get("distractor1", "")
            distractor2 = question.get("distractor2", "")
            distractor3 = question.get("distractor3", "")
            explanation = question.get("explanation", "")
            
            if not explanation:
                explanation = "The correct answer is " + correct_answer
            
            # Map the difficulty level
            difficulty_str = question.get("difficulty", "1")
            try:
                difficulty = int(difficulty_str)
            except ValueError:
                # Handle string difficulty levels (convert to numeric)
                difficulty_map = {"easy": 1, "medium": 2, "hard": 3}
                difficulty = difficulty_map.get(difficulty_str.lower(), 1)
            
            # Format the responses with explanation for each option
            responses = [
                {"label": correct_answer, "isCorrect": True, "explanation": ""},
                {"label": distractor1, "isCorrect": False, "explanation": ""},
                {"label": distractor2, "isCorrect": False, "explanation": ""},
                {"label": distractor3, "isCorrect": False, "explanation": ""}
            ]
            
            # Add the formatted question to the list
            formatted_questions.append({
                "material": question_text,
                "referenceText": passage_text,
                "explanation": explanation,
                "responses": responses,
                "difficulty": difficulty
            })
        
        # Create the full API payload - EXACTLY matching Option 1
        payload = {
            "content": [
                {
                    "content": formatted_questions,  # Direct array of question objects
                    "content_type": "Question"
                }
            ],
            "course_details": course_details
        }
        
        return payload
    
    async def get_course_details_from_user(self) -> Dict[str, Any]:
        """
        Gets course details from the user for a NEW course.
        
        Returns:
            A dictionary containing course details
        """
        print("\nPlease provide the following course details:")
        
        course_title = input("Course title: ")
        module_name = input("Module name: ")
        item_name = input("Item name: ")
        
        try:
            xp_value = int(input("XP value (points for completing this quiz): "))
        except ValueError:
            logger.warning("Invalid XP value entered. Defaulting to 10.")
            xp_value = 10
        
        # Create the course details structure
        course_details = {
            "course": {"title": course_title},
            "module": {"name": module_name},
            "items": [
                {
                    "name": item_name,
                    "contentType": "quiz",
                    "xp": xp_value
                }
            ]
        }
        
        return course_details
        
    async def get_existing_course_details(self) -> Dict[str, Any]:
        """
        Gets details for updating an existing course with a new module.
        
        Returns:
            A dictionary containing course details with course_id
        """
        print("\nPlease provide the following details to add content to an existing course:")
        
        course_id = input("Course ID: ")
        
        # Validate that the course ID is not empty
        while not course_id.strip():
            print("Course ID cannot be empty.")
            course_id = input("Course ID: ")
        
        module_name = input("New module name: ")
        item_name = input("Quiz name: ")
        
        try:
            xp_value = int(input("XP value (points for completing this quiz): "))
        except ValueError:
            logger.warning("Invalid XP value entered. Defaulting to 10.")
            xp_value = 10
        
        # Create the course details structure for existing course
        course_details = {
            "module": {"name": module_name},
            "items": [
                {
                    "name": item_name,
                    "contentType": "quiz",
                    "xp": xp_value
                }
            ],
            "course_id": course_id
        }
        
        return course_details
    
    async def get_existing_module_details(self) -> Dict[str, Any]:
        """
        Gets details for updating an existing module in an existing course.
        
        Returns:
            A dictionary containing course details with course_id and module_id
        """
        print("\nPlease provide the following details to update an existing module in an existing course:")
        
        course_id = input("Course ID: ")
        
        # Validate that the course ID is not empty
        while not course_id.strip():
            print("Course ID cannot be empty.")
            course_id = input("Course ID: ")
        
        module_id = input("Module ID: ")
        
        # Validate that the module ID is not empty
        while not module_id.strip():
            print("Module ID cannot be empty.")
            module_id = input("Module ID: ")
        
        item_name = input("Quiz name: ")
        
        try:
            xp_value = int(input("XP value (points for completing this quiz): "))
        except ValueError:
            logger.warning("Invalid XP value entered. Defaulting to 10.")
            xp_value = 10
        
        # Create the course details structure for existing module
        course_details = {
            "items": [
                {
                    "name": item_name,
                    "contentType": "quiz",
                    "xp": xp_value
                }
            ],
            "course_id": course_id,
            "module_id": module_id
        }
        
        return course_details
    
    @with_retry(
        max_retries=config.MAX_RETRIES,
        retry_delay=config.RETRY_DELAY,
        exceptions_to_retry=[
            requests.RequestException,
            requests.ConnectionError,
            requests.Timeout,
            ValueError,
            Exception
        ],
        timeout=config.API_TIMEOUT
    )
    async def publish_to_api(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Publishes the quiz to the API.
        
        Args:
            payload: The API payload
            
        Returns:
            The API response
        """
        logger.info(f"Publishing quiz to API at {self.endpoint}")
        
        headers = {
            "Content-Type": "application/json"
            # No Authorization header needed
        }
        
        # Using asyncio.to_thread to run the blocking request in a separate thread
        response = await asyncio.to_thread(
            lambda: requests.post(
                url=self.endpoint,
                headers=headers,
                json=payload,
                timeout=60  # Timeout in seconds
            )
        )
        
        # Check for successful response
        response.raise_for_status()
        
        # Parse the response JSON
        try:
            response_data = response.json()
            logger.info("Successfully published quiz to API")
            return response_data
        except ValueError:
            error_msg = f"Invalid JSON response from API: {response.text[:100]}..."
            logger.error(error_msg)
            raise ValueError(error_msg)
    
    async def save_quiz_to_file(self, quiz: Dict[str, Any], filename: str = None) -> str:
        """
        Saves the quiz to a JSON file.
        
        Args:
            quiz: The quiz to save
            filename: Optional filename to save to
            
        Returns:
            The path to the saved file
        """
        # Use the configured output directory
        output_dir = config.OUTPUT_DIR
        
        # Create the output directory if it doesn't exist
        if output_dir and not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
                logger.info(f"Created output directory: {output_dir}")
            except Exception as e:
                logger.warning(f"Could not create output directory {output_dir}: {str(e)}")
                output_dir = ""  # Fall back to current directory
        
        if not filename:
            # Generate a filename based on quiz metadata
            metadata = quiz.get("metadata", {})
            lesson_name = metadata.get("lesson_name", "unknown")
            standard_id = metadata.get("standard_id", "unknown")
            timestamp = metadata.get("timestamp", "").replace(' ', '_').replace(':', '-')
            
            filename = f"quiz_{lesson_name}_{standard_id}_{timestamp}.json"
            # Remove any invalid characters
            filename = ''.join(c if c.isalnum() or c in '._-' else '_' for c in filename)
            
            # Prepend the output directory
            if output_dir:
                filename = os.path.join(output_dir, filename)
        
        try:
            # Ensure directory exists
            file_path = pathlib.Path(filename)
            file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write the file
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(quiz, f, indent=2)
            logger.info(f"Quiz saved to file: {filename}")
            return filename
        except Exception as e:
            logger.error(f"Error saving quiz to file: {str(e)}")
            # Try with a simplified filename
            simplified_filename = f"quiz_{hash(str(quiz))}.json"
            if output_dir:
                simplified_filename = os.path.join(output_dir, simplified_filename)
                
            try:
                with open(simplified_filename, 'w', encoding='utf-8') as f:
                    json.dump(quiz, f, indent=2)
                logger.info(f"Quiz saved to file with simplified name: {simplified_filename}")
                return simplified_filename
            except Exception as e2:
                logger.error(f"Error saving quiz with simplified filename: {str(e2)}")
                raise
    
    async def process_quiz(self, quiz: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a quiz - ask the user if they want to publish it,
        save it to a file, and optionally publish it to the API.
        
        Args:
            quiz: The quiz to process
            
        Returns:
            A dictionary with the results of the processing
        """
        result = {
            "success": False,
            "actions": [],
            "messages": []
        }
        
        try:
            # First, save the quiz to a file
            saved_file = await self.save_quiz_to_file(quiz)
            result["actions"].append("saved")
            result["saved_file"] = saved_file
            result["messages"].append(f"Quiz saved to {saved_file}")
            
            # Ask the user if they want to publish the quiz
            publish_response = await self.ask_user("Do you want to publish this quiz to the database? (yes/no)")
            
            if publish_response not in ['yes', 'y']:
                result["messages"].append("User chose not to publish the quiz.")
                result["success"] = True
                return result
            
            # User wants to publish, ask what kind of publishing they want
            course_choice = await self.ask_user("Do you want to create a new course, add to an existing course, or update an existing module? (new/add/update)")
            
            if course_choice in ['new', 'n']:
                # Get details for new course
                course_details = await self.get_course_details_from_user()
                
                # Format the quiz for the API
                payload = self.format_quiz_for_api(quiz, course_details)
                
                # Publish to the API
                api_response = await self.publish_to_api(payload)
                
                result["actions"].append("published_new_course")
                result["api_response"] = api_response
                result["messages"].append("Quiz successfully published as a new course.")
                result["success"] = True
            elif course_choice in ['add', 'a', 'existing', 'e']:
                # Get details for existing course
                course_details = await self.get_existing_course_details()
                
                # Format the quiz for the API
                payload = self.format_quiz_for_api(quiz, course_details)
                
                # Publish to the API
                api_response = await self.publish_to_api(payload)
                
                result["actions"].append("published_to_existing_course")
                result["api_response"] = api_response
                result["messages"].append("Quiz successfully published to existing course as a new module.")
                result["success"] = True
            elif course_choice in ['update', 'u']:
                # Get details for existing module
                course_details = await self.get_existing_module_details()
                
                # Format the quiz for the API
                payload = self.format_quiz_for_api(quiz, course_details)
                
                # Publish to the API
                api_response = await self.publish_to_api(payload)
                
                result["actions"].append("updated_existing_module")
                result["api_response"] = api_response
                result["messages"].append("Quiz successfully updated in existing module.")
                result["success"] = True
            else:
                result["messages"].append("Invalid choice. Quiz was not published.")
                result["success"] = False
        
        except Exception as e:
            logger.error(f"Error processing quiz: {str(e)}")
            result["messages"].append(f"Error: {str(e)}")
        
        return result

    async def publish_quiz_to_api(self, payload: dict) -> dict:
        """Publish a quiz to the API."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.endpoint,
                    json=payload,
                    timeout=self.timeout  # Use the instance timeout
                ) as response:
                    response_data = await response.json()
                    
                    if response.status == 200:
                        logger.info("Successfully published quiz to API")
                        return response_data
                    else:
                        error_message = response_data.get('detail', str(response_data))
                        logger.error(f"Failed to publish quiz: {response.status} - {error_message}")
                        raise Exception(f"API error {response.status}: {error_message}")
        except aiohttp.ClientResponseError as e:
            logger.error(f"ClientResponseError: {e.status} - {e.message}")
            raise Exception(f"API error {e.status}: {e.message}")
        except aiohttp.ClientError as e:
            logger.error(f"ClientError: {str(e)}")
            raise Exception(f"Client error: {str(e)}")
        except Exception as e:
            logger.error(f"Failed Publishing data to powerpath: {str(e)}")
            raise Exception(f"Failed Publishing data to powerpath: {str(e)}")
            
    def check_publish_success(self, response: dict) -> bool:
        """Check if publishing was successful based on API response."""
        return response and "course_id" in response

# Example usage
async def main():
    """
    Example usage of the PublishQuestions class.
    """
    try:
        # Create sample quiz data
        sample_quiz = {
            "passage": {
                "id": "sample",
                "title": "Sample Passage",
                "author": "Sample Author",
                "type": "Text",
                "text": "<p>This is a sample passage.</p>"
            },
            "questions": [
                {
                    "question": "What is the main topic of the passage?",
                    "correct_answer": "The correct answer",
                    "distractor1": "Wrong answer 1",
                    "distractor2": "Wrong answer 2",
                    "distractor3": "Wrong answer 3",
                    "difficulty": "1",
                    "standard": "RL.1",
                    "explanation": "The correct answer is..."
                }
            ],
            "metadata": {
                "lesson_name": "sample_lesson",
                "standard_id": "RL.1",
                "difficulty": 1,
                "num_questions": 1,
                "num_questions_generated": 1,
                "timestamp": "2023-05-01 12:00:00"
            }
        }
        
        # Process the quiz
        publisher = PublishQuestions()
        result = await publisher.process_quiz(sample_quiz)
        
        # Print the result
        print(json.dumps(result, indent=2))
    
    except Exception as e:
        print(f"Error in main: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main()) 