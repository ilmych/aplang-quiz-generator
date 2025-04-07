import json
import asyncio
import random
import os
import re
import datetime
from typing import Dict, List, Any, Tuple, Optional
import anthropic
from functools import partial
from quality_control import QuestionQualityControl

# Import centralized logging configuration
from logging_config import logger

# Import centralized configuration
from config import config

# Import utility functions
from utils import with_retry

# Import dotenv to load environment variables (already loaded in config)
import sys

# Import dotenv for environment variables (already loaded in config)
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Constants moved to config.py, use references here
ANTHROPIC_API_KEY = config.ANTHROPIC_API_KEY
MAX_RETRIES = config.MAX_RETRIES
RETRY_DELAY = config.RETRY_DELAY
MODEL = config.MODEL
MAX_WORKERS = config.MAX_WORKERS

# File paths from config
LESSONS_FILE = config.LESSONS_FILE
PASSAGES_FILE = config.PASSAGES_FILE
EXAMPLES_FILE = config.EXAMPLES_FILE

# Difficulty level mappings and map from config
DIFFICULTY_LEVELS = config.DIFFICULTY_LEVELS
DIFFICULTY_MAP = config.DIFFICULTY_MAP

# Log API key status (without revealing the actual key)
if not ANTHROPIC_API_KEY:
    logger.warning("No ANTHROPIC_API_KEY found in environment. API calls will fail.")
else:
    # Log part of the key for verification (first 4 chars and last 4 chars)
    if len(ANTHROPIC_API_KEY) > 8:
        key_preview = f"{ANTHROPIC_API_KEY[:4]}...{ANTHROPIC_API_KEY[-4:]}"
        logger.info(f"API key loaded: {key_preview}")

# Log configuration
config.log_config(logger)

# Initialize Anthropic client
try:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    # Test the API key validity with a simple operation
    client.api_key  # Just access the property to verify it's set
    logger.info("Anthropic client initialized successfully")
except Exception as e:
    logger.warning(f"Error initializing Anthropic client: {str(e)}. Will attempt to initialize later.")
    client = None

class QuizGenerator:
    def __init__(self):
        self.lessons_data = []
        self.passages_data = []
        self.examples_data = []
        self.standards_by_lesson = {}
        self.lessons_by_standard = {}
        self.passages_by_standard = {}
        self.examples_by_standard_and_difficulty = {}
        self.quality_control = QuestionQualityControl()
        self.load_data()
    
    def load_data(self):
        """
        Load all necessary data from JSON files:
        - Standards for each lesson (lang_lessons.json)
        - Passages database with standards (lang_passages.json)
        - Question examples for standards and difficulties (lang_examples.json)
        """
        files_to_load = [
            (LESSONS_FILE, "lessons"),
            (PASSAGES_FILE, "passages"),
            (EXAMPLES_FILE, "examples")
        ]
        
        loaded_data = {}
        
        # First, check if all required files exist
        missing_files = []
        for file_path, data_type in files_to_load:
            if not os.path.exists(file_path):
                missing_files.append(file_path)
        
        if missing_files:
            missing_files_str = ", ".join(missing_files)
            error_msg = f"Required data files not found: {missing_files_str}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)
        
        # Load all data files
        logger.info("Loading data from JSON files...")
        
        try:
            # Load lessons and standards
            with open(LESSONS_FILE, 'r', encoding='utf-8') as f:
                self.lessons_data = json.load(f)
                if not self.lessons_data:
                    logger.warning(f"No lessons found in {LESSONS_FILE}")
                else:
                    logger.info(f"Loaded {len(self.lessons_data)} lessons from {LESSONS_FILE}")
            
            # Create mappings for easier lookup
            # Map lessons to standards (one lesson can have multiple standards)
            # Map standards to lessons (one standard can be in multiple lessons)
            for lesson_data in self.lessons_data:
                lesson_name = lesson_data.get("lesson")
                standards = lesson_data.get("standards", "")
                
                if not lesson_name:
                    logger.warning(f"Skipping lesson data without name: {lesson_data}")
                    continue
                    
                if not standards:
                    logger.warning(f"Lesson '{lesson_name}' has no associated standards")
                    standards = ""
                
                # Convert standards to list if it's a string
                if isinstance(standards, str):
                    # Split the standards string by comma and trim whitespace
                    standards_list = [std.strip() for std in standards.split(',') if std.strip()]
                else:
                    # If it's already a list, use it directly
                    standards_list = standards
                    
                # Map lesson to its standards
                self.standards_by_lesson[lesson_name] = standards_list
                
                # Map each standard to the lessons it's in
                for standard in standards_list:
                    if standard not in self.lessons_by_standard:
                        self.lessons_by_standard[standard] = []
                    if lesson_name not in self.lessons_by_standard[standard]:
                        self.lessons_by_standard[standard].append(lesson_name)
            
            if not self.standards_by_lesson:
                logger.warning("No lesson-to-standards mappings created. Check data format in lessons file.")
            else:
                logger.info(f"Mapped {len(self.standards_by_lesson)} lessons to their standards")
                
            if not self.lessons_by_standard:
                logger.warning("No standard-to-lessons mappings created. Check data format in lessons file.")
            else:
                logger.info(f"Mapped {len(self.lessons_by_standard)} standards to their lessons")
            
            # Load passages
            with open(PASSAGES_FILE, 'r', encoding='utf-8') as f:
                self.passages_data = json.load(f)
                if not self.passages_data:
                    logger.warning(f"No passages found in {PASSAGES_FILE}")
                else:
                    logger.info(f"Loaded {len(self.passages_data)} passages from {PASSAGES_FILE}")
            
            # Create passage-to-standard mappings from passage data
            self.passages_by_standard = {}  # Initialize empty dictionary
            
            # Process the standards field in each passage
            for passage in self.passages_data:
                passage_id = passage.get("id")
                standards_str = passage.get("standards", "")

                if not passage_id:
                    logger.warning(f"Skipping passage without ID: {passage.get('title', 'Unknown title')}")
                    continue
                
                # Handle null or missing standards gracefully
                if not standards_str:
                    logger.warning(f"Passage has no standards: {passage_id} - {passage.get('title', 'Unknown title')}")
                    standards = []
                else:
                    # Split the standards string into a list of individual standards
                    standards = [std.strip() for std in standards_str.split(',') if std.strip()]
                
                # Add passage to each of its standards
                for standard in standards:
                    if standard not in self.passages_by_standard:
                        self.passages_by_standard[standard] = []
                    self.passages_by_standard[standard].append(passage)
            
            # Initialize empty mappings for any standards that don't have passages
            for standard in self.lessons_by_standard.keys():
                if standard not in self.passages_by_standard:
                    self.passages_by_standard[standard] = []
                    logger.warning(f"Standard '{standard}' has no associated passages")
            
            # Log statistics about passages and standards
            standards_with_passages = sum(1 for passages in self.passages_by_standard.values() if passages)
            total_mappings = sum(len(passages) for passages in self.passages_by_standard.values())
            logger.info(f"Found {standards_with_passages} standards with at least one passage")
            logger.info(f"Created {total_mappings} passage-standard mappings")
            
            # Load example questions
            with open(EXAMPLES_FILE, 'r', encoding='utf-8') as f:
                self.examples_data = json.load(f)
                if not self.examples_data:
                    logger.warning(f"No example questions found in {EXAMPLES_FILE}")
                else:
                    logger.info(f"Loaded {len(self.examples_data)} example questions from {EXAMPLES_FILE}")
            
            # Map examples
            self._map_examples_by_standard_and_difficulty()
            
            # Validate data
            self._validate_data()
            
            logger.info("Data loaded successfully")
            
        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON in data file: {str(e)}"
            logger.error(error_msg)
            raise ValueError(error_msg)
        except Exception as e:
            error_msg = f"Error loading data: {str(e)}"
            logger.error(error_msg)
            raise
    
    def _validate_data(self):
        """
        Validate that we have sufficient data to generate quizzes
        """
        # Check if we have lessons
        if not self.lessons_data:
            logger.warning("No lessons found in lessons data")
            
        # Check if we have passages
        if not self.passages_data:
            logger.warning("No passages found in passages data")
            
        # Check if we have example questions
        if not self.examples_data:
            logger.warning("No example questions found in examples data")
            
        # Check standards coverage
        missing_standards = []
        for standard in self.lessons_by_standard:
            if standard not in self.passages_by_standard or not self.passages_by_standard[standard]:
                missing_standards.append(standard)
                
        if missing_standards:
            logger.warning(f"The following standards have no associated passages: {', '.join(missing_standards)}")
            
        # Check for standards with insufficient example questions
        insufficient_examples = []
        for standard in self.lessons_by_standard:
            for difficulty in ["1", "2", "3"]:
                if (standard, difficulty) not in self.examples_by_standard_and_difficulty or \
                   not self.examples_by_standard_and_difficulty[(standard, difficulty)]:
                    insufficient_examples.append(f"{standard} (difficulty {difficulty})")
                    
        if insufficient_examples:
            logger.warning(f"The following standard-difficulty pairs have no example questions: {', '.join(insufficient_examples)}")
            
        # All validations passed
        logger.info("Data validation completed")
    
    def _map_examples_by_standard_and_difficulty(self):
        """
        Map example questions by standard and difficulty level
        """
        for example in self.examples_data:
            standard = example.get("standard")
            difficulty = example.get("difficulty")
            
            if not standard or not difficulty:
                continue
                
            key = (standard, difficulty)
            if key not in self.examples_by_standard_and_difficulty:
                self.examples_by_standard_and_difficulty[key] = []
                
            self.examples_by_standard_and_difficulty[key].append(example)

    def _handle_missing_data(self, standard_id: str = None, lesson_name: str = None) -> Dict[str, Any]:
        """
        Provides graceful fallback when data is missing or invalid.
        Attempts to generate a basic quiz that can work despite missing data.
        
        Args:
            standard_id: Optional standard ID that was requested
            lesson_name: Optional lesson name that was requested
            
        Returns:
            A basic quiz structure that can be returned to the user
        """
        logger.warning(f"Generating basic fallback quiz due to missing data. Standard: {standard_id}, Lesson: {lesson_name}")
        
        # Try to find any passage
        passage = None
        
        # If we have any passages, use the first one
        if self.passages_data:
            passage = self.passages_data[0]
            logger.info(f"Using fallback passage: {passage.get('title', 'Unknown')}")
        else:
            # Create a minimal passage
            passage = {
                "id": "fallback",
                "title": "Sample Passage",
                "author": "System Generated",
                "type": "Text",
                "text": "<p>This is a sample passage generated because the requested data was not available. The system could not find the necessary passage data for your quiz.</p>"
            }
            logger.warning("Created minimal fallback passage due to completely missing data")
        
        # Create a basic quiz with minimal questions
        quiz = {
            "passage": {
                "id": passage.get("id", "fallback"),
                "title": passage.get("title", "Sample Passage"),
                "author": passage.get("author", "System Generated"),
                "type": passage.get("type", "Text"),
                "text": passage.get("text", "<p>Sample text</p>")
            },
            "questions": [],
            "metadata": {
                "lesson_name": lesson_name,
                "standard_id": standard_id,
                "difficulty": 1,
                "num_questions": 0,
                "num_questions_generated": 0,
                "timestamp": self.get_timestamp(),
                "error": "Insufficient data available to generate a complete quiz. This is a fallback result."
            }
        }
        
        logger.warning("Returning fallback quiz with 0 questions")
        return quiz
    
    async def generate_quiz(self, 
                    lesson_name: str = None, 
                    standard_id: str = None, 
                    difficulty: int = 1, 
                    num_questions: int = 6) -> Dict[str, Any]:
        """
        Main function to generate a complete quiz
        
        Args:
            lesson_name: Name of the lesson to create quiz for
            standard_id: Alternative to lesson_name, specific standard to quiz
            difficulty: Quiz difficulty (1, 2, or 3)
            num_questions: Number of questions to generate (6-12)
            
        Returns:
            Complete quiz as a JSON-serializable dictionary
        """
        logger.info(f"Generating quiz with: {'Lesson: '+lesson_name if lesson_name else 'Standard: '+standard_id}, Difficulty: {difficulty}, Questions: {num_questions}")
        
        try:
            # Get the standards for this quiz
            lesson_standards = []
            if lesson_name and not standard_id:
                lesson_standards = self.get_standards_for_lesson(lesson_name)
                if not lesson_standards:
                    logger.error(f"No standards found for lesson: {lesson_name}")
                    return self._handle_missing_data(lesson_name=lesson_name)
                    
                # If we have multiple standards for this lesson, use them all
                # for appropriate question distribution
                logger.info(f"Found {len(lesson_standards)} standards for lesson: {lesson_name}")
            
            elif standard_id:
                # If a specific standard was provided, use just that one
                if isinstance(standard_id, list):
                    lesson_standards = standard_id
                else:
                    lesson_standards = [standard_id]
                    
            if not lesson_standards:
                logger.error("Neither lesson_name nor standard_id was provided")
                return self._handle_missing_data()
                
            # Get all standards up to this point in the curriculum
            all_previous_standards = []
            for std in lesson_standards:
                previous_standards = self.get_previous_standards(std)
                for prev_std in previous_standards:
                    if prev_std not in all_previous_standards:
                        all_previous_standards.append(prev_std)
                
            # Select a passage for the quiz
            # Try to find a passage that works for all lesson standards
            passage = None
            if len(lesson_standards) > 1:
                common_passages = None
                for std in lesson_standards:
                    std_passages = self.passages_by_standard.get(std, [])
                    
                    if not std_passages:
                        logger.warning(f"No passages found for standard: {std}")
                        continue
                        
                    if common_passages is None:
                        common_passages = set(std_passages)
                    else:
                        common_passages &= set(std_passages)
                
                if common_passages:
                    passage = random.choice(list(common_passages))
                    logger.info(f"Found passage that covers all {len(lesson_standards)} standards")
                else:
                    logger.warning(f"No passage covers all standards. Selecting passage for first standard.")
            
            if not passage:
                # If no common passage or only one standard, pick a passage for the first standard
                primary_standard = lesson_standards[0]
                passages = self.passages_by_standard.get(primary_standard, [])
                
                if not passages:
                    logger.error(f"No suitable passage found for standard {primary_standard}")
                    return self._handle_missing_data(standard_id=primary_standard, lesson_name=lesson_name)
                    
                passage = random.choice(passages)
                logger.info(f"Selected passage for standard: {primary_standard}")
                
            # Determine question distribution based on difficulty and standards
            question_distribution = self.distribute_questions(
                num_questions, 
                difficulty, 
                lesson_standards,
                all_previous_standards
            )
            
            # Generate questions
            try:
                # Use await to properly handle the coroutine
                questions = await self.generate_questions(passage, question_distribution)
            except Exception as e:
                logger.error(f"Error generating questions: {str(e)}")
                # Return a partial quiz with the passage but no questions
                quiz = self.format_quiz_output([], passage)
                # Add error information to metadata
                quiz["metadata"] = {
                    "lesson_name": lesson_name,
                    "standard_id": standard_id if standard_id else (self.standards_by_lesson.get(lesson_name) if lesson_name else None),
                    "difficulty": difficulty,
                    "num_questions": num_questions,
                    "num_questions_generated": 0,
                    "timestamp": self.get_timestamp(),
                    "error": f"Failed to generate questions: {str(e)}"
                }
                return quiz
            
            # Format the quiz for output
            quiz = self.format_quiz_output(questions, passage)
            
            # Add metadata to the quiz
            quiz["metadata"] = {
                "lesson_name": lesson_name,
                "standard_id": standard_id if standard_id else (self.standards_by_lesson.get(lesson_name, [None])[0] if lesson_name else None),
                "difficulty": difficulty,
                "num_questions": num_questions,
                "num_questions_generated": len(quiz.get("questions", [])),
                "timestamp": self.get_timestamp()
            }
            
            return quiz
        
        except Exception as e:
            logger.error(f"Unexpected error in generate_quiz: {str(e)}", exc_info=True)
            return self._handle_missing_data(standard_id=standard_id, lesson_name=lesson_name)
    
    def get_standards_for_lesson(self, lesson_name: str) -> List[str]:
        """
        Find the standards associated with a lesson
        
        Args:
            lesson_name: Name of the lesson
            
        Returns:
            List of standard IDs associated with the lesson
        """
        standards = self.standards_by_lesson.get(lesson_name, [])
        if not standards:
            logger.warning(f"No standards found for lesson: {lesson_name}")
            return []
            
        return standards
    
    def get_previous_standards(self, current_standard: str) -> List[str]:
        """
        Get all standards that appear before the current standard in the curriculum
        
        Args:
            current_standard: The current standard ID
            
        Returns:
            List of standard IDs that appear earlier in the curriculum
        """
        # This is a simplified implementation - your actual ordering logic may differ
        all_standards = list(self.lessons_by_standard.keys())
        
        if current_standard not in all_standards:
            return all_standards
            
        current_index = all_standards.index(current_standard)
        return all_standards[:current_index + 1]  # Include current standard
    
    def select_passage(self, standard_id: str) -> Dict[str, Any]:
        """
        Select an appropriate passage for the given standard
        
        Args:
            standard_id: ID of the standard
            
        Returns:
            Passage data dictionary
        """
        if isinstance(standard_id, list):
            # Try to find a passage that works for all standards
            common_passages = None
            for std in standard_id:
                passages = self.passages_by_standard.get(std, [])
                if common_passages is None:
                    common_passages = set(passages)
                else:
                    common_passages &= set(passages)
            
            if common_passages:
                return random.choice(list(common_passages))
            
            # Fallback: just pick a passage for the first standard
            std = standard_id[0]
            passages = self.passages_by_standard.get(std, [])
        else:
            passages = self.passages_by_standard.get(standard_id, [])
        
        if not passages:
            return None
            
        return random.choice(passages)
    
    def distribute_questions(self, 
                           num_questions: int, 
                           difficulty: int, 
                           lesson_standards: List[str],
                           all_standards: List[str]) -> Dict[str, Dict[str, int]]:
        """
        Determine the distribution of questions based on difficulty and standards
        
        Args:
            num_questions: Total number of questions to generate
            difficulty: Quiz difficulty level (1, 2, or 3)
            lesson_standards: Standards covered by the current lesson
            all_standards: All standards up to the current lesson
            
        Returns:
            Dictionary mapping standard IDs to difficulty distributions
            Example: {"standard1": {"easy": 2, "medium": 1, "hard": 0}, ...}
        """
        logger.info(f"Distributing {num_questions} questions across standards and difficulty levels")
        logger.info(f"Quiz difficulty: {difficulty}")
        logger.info(f"Lesson standards: {lesson_standards}")
        
        # Step 1: Determine difficulty distribution based on quiz difficulty level
        diff_ranges = DIFFICULTY_LEVELS.get(difficulty, DIFFICULTY_LEVELS[1])
        
        # Determine min/max questions for each difficulty level
        easy_min, easy_max = diff_ranges["easy"]
        medium_min, medium_max = diff_ranges["medium"]
        hard_min, hard_max = diff_ranges["hard"]
        
        # Ensure the distribution is possible with the requested number of questions
        min_total = easy_min + medium_min + hard_min
        if min_total > num_questions:
            # Scale down if necessary while preserving relative proportions
            scale = num_questions / min_total
            easy_min = max(1, int(easy_min * scale))
            medium_min = max(1, int(medium_min * scale))
            hard_min = max(1, int(hard_min * scale))
            logger.warning(f"Scaling down minimum question counts due to low total questions: {num_questions}")
        
        # Randomize within the ranges, but ensure minimum requirements are met
        # Start with maximum values capped by remaining questions
        max_easy = min(easy_max, num_questions - medium_min - hard_min)
        logger.info(f"Easy range: min={easy_min}, max={max_easy}")
        
        # Check if the range is valid (max should be >= min)
        if max_easy < easy_min:
            logger.warning(f"Invalid easy range: min={easy_min}, max={max_easy}. Using min value.")
            num_easy = min(easy_min, num_questions)  # Cap at total questions
            logger.info(f"Adjusted easy count: {num_easy}")
        elif max_easy == easy_min:
            num_easy = easy_min  # If range is empty, use the minimum value
            logger.info(f"Using easy_min directly: {num_easy}")
        else:
            num_easy = random.randint(easy_min, max_easy)
            logger.info(f"Randomly selected easy count: {num_easy}")
        
        remaining = num_questions - num_easy
        max_medium = min(medium_max, remaining - hard_min)
        logger.info(f"Medium range: min={medium_min}, max={max_medium}")
        
        # Check if the range is valid (max should be >= min)
        if max_medium < medium_min:
            logger.warning(f"Invalid medium range: min={medium_min}, max={max_medium}. Using min value.")
            num_medium = min(medium_min, remaining)  # Cap at remaining questions
            logger.info(f"Adjusted medium count: {num_medium}")
        elif max_medium == medium_min:
            num_medium = medium_min  # If range is empty, use the minimum value
            logger.info(f"Using medium_min directly: {num_medium}")
        else:
            num_medium = random.randint(medium_min, max_medium)
            logger.info(f"Randomly selected medium count: {num_medium}")
        
        num_hard = num_questions - num_easy - num_medium
        logger.info(f"Hard count (remainder): {num_hard}")
        
        logger.info(f"Difficulty distribution: {num_easy} easy, {num_medium} medium, {num_hard} hard")
        
        # Step 2: Distribute questions by standard
        # First, ensure each lesson standard gets its minimum quota
        questions_per_standard = {}
        questions_left = num_questions
        
        # The minimum questions per lesson standard depends on how many lesson standards we have
        num_lesson_standards = len(lesson_standards)
        if num_lesson_standards == 0:
            min_questions_per_lesson_standard = 0
            logger.warning("No lesson standards provided")
        elif num_lesson_standards == 1:
            # If only one standard, ensure at least 3 questions (as per requirements)
            min_questions_per_lesson_standard = min(3, num_questions)
        else:
            # If multiple standards, ensure at least 2 per standard (as per requirements)
            min_questions_per_lesson_standard = min(2, num_questions // num_lesson_standards)
        
        # Assign minimum questions to lesson standards
        for std in lesson_standards:
            if questions_left <= 0:
                break
                
            questions_for_std = min(min_questions_per_lesson_standard, questions_left)
            questions_per_standard[std] = questions_for_std
            questions_left -= questions_for_std
            
        logger.info(f"Assigned minimum of {min_questions_per_lesson_standard} questions per lesson standard")
        
        # Create a list of standards ordered by priority:
        # 1. Lesson standards first (to potentially get more than minimum)
        # 2. Earlier standards in the curriculum next
        # Remove standards already at their limit
        prioritized_standards = []
        
        # Add lesson standards first (for additional questions beyond minimum)
        for std in lesson_standards:
            prioritized_standards.append(std)
        
        # Then add earlier standards (excluding lesson standards)
        for std in all_standards:
            if std not in lesson_standards:
                prioritized_standards.append(std)
        
        # Distribute remaining questions among available standards
        # Use weighted random selection that favors standards earlier in the list
        while questions_left > 0 and prioritized_standards:
            # Calculate weights - earlier standards get higher weights
            logger.info(f"Prioritized standards count: {len(prioritized_standards)}")
            
            if len(prioritized_standards) == 1:
                # If only one standard is available, just use it
                std = prioritized_standards[0]
                logger.info(f"Only one standard available, using: {std}")
            else:
                weights = [max(1, len(prioritized_standards) - i) for i in range(len(prioritized_standards))]
                
                # Select a standard based on weights
                std = random.choices(prioritized_standards, weights=weights, k=1)[0]
            
            # Update the count for this standard
            if std not in questions_per_standard:
                questions_per_standard[std] = 0
            
            questions_per_standard[std] += 1
            questions_left -= 1
            
            # Remove standards that have reached a reasonable maximum per standard
            # Set a cap of ~25% of total questions per standard to ensure variety
            max_per_standard = max(3, num_questions // 4)
            if questions_per_standard[std] >= max_per_standard:
                prioritized_standards.remove(std)
        
        # If we still have questions left, distribute them evenly across all standards
        if questions_left > 0:
            logger.warning(f"Distributing {questions_left} remaining questions across all standards")
            all_stds = list(questions_per_standard.keys())
            while questions_left > 0 and all_stds:
                std = random.choice(all_stds)
                questions_per_standard[std] += 1
                questions_left -= 1
        
        # Step 3: Distribute difficulty levels across standards
        # Strategy: Prioritize harder questions for the main lesson standards
        result = {}
        easy_left, medium_left, hard_left = num_easy, num_medium, num_hard
        
        # First, distribute hard questions to lesson standards
        for std in lesson_standards:
            if std not in questions_per_standard:
                continue
                
            count = questions_per_standard[std]
            result[std] = {"easy": 0, "medium": 0, "hard": 0}
            
            # Allocate hard questions to lesson standards first
            hard_for_std = min(count, hard_left)
            result[std]["hard"] = hard_for_std
            hard_left -= hard_for_std
            count -= hard_for_std
            
            # Then allocate medium and easy
            if count > 0:
                medium_for_std = min(count, medium_left)
                result[std]["medium"] = medium_for_std
                medium_left -= medium_for_std
                count -= medium_for_std
            
            if count > 0:
                easy_for_std = min(count, easy_left)
                result[std]["easy"] = easy_for_std
                easy_left -= easy_for_std
                count -= easy_for_std
        
        # Then distribute remaining questions to non-lesson standards
        for std, count in questions_per_standard.items():
            if std in lesson_standards:
                continue  # Already handled
                
            result[std] = {"easy": 0, "medium": 0, "hard": 0}
            
            # For non-lesson standards, prioritize easy, then medium, then hard
            if count > 0 and easy_left > 0:
                easy_for_std = min(count, easy_left)
                result[std]["easy"] = easy_for_std
                easy_left -= easy_for_std
                count -= easy_for_std
            
            if count > 0 and medium_left > 0:
                medium_for_std = min(count, medium_left)
                result[std]["medium"] = medium_for_std
                medium_left -= medium_for_std
                count -= medium_for_std
            
            if count > 0 and hard_left > 0:
                hard_for_std = min(count, hard_left)
                result[std]["hard"] = hard_for_std
                hard_left -= hard_for_std
                count -= hard_for_std
        
        # If there are still questions to distribute (due to standards reaching limits),
        # randomly assign them to standards that can accommodate more
        remaining_difficulty_counts = {
            "easy": easy_left,
            "medium": medium_left,
            "hard": hard_left
        }
        
        # Log if we have leftover questions
        total_leftover = easy_left + medium_left + hard_left
        if total_leftover > 0:
            logger.warning(f"Had {total_leftover} leftover questions to redistribute: {remaining_difficulty_counts}")
            
            # Find standards that can take more questions
            for diff, count in list(remaining_difficulty_counts.items()):
                while count > 0:
                    # Find standards with the fewest questions of this difficulty
                    min_count = float('inf')
                    eligible_standards = []
                    
                    for std in result:
                        if result[std][diff] < min_count:
                            min_count = result[std][diff]
                            eligible_standards = [std]
                        elif result[std][diff] == min_count:
                            eligible_standards.append(std)
                    
                    if not eligible_standards:
                        logger.error(f"Could not find standards to assign remaining {diff} questions")
                        break
                        
                    # Pick a random eligible standard and add one question
                    std = random.choice(eligible_standards)
                    result[std][diff] += 1
                    count -= 1
                    remaining_difficulty_counts[diff] = count
        
        # Final validation
        total_distributed = sum(sum(counts.values()) for counts in result.values())
        if total_distributed != num_questions:
            logger.error(f"Question distribution error: Distributed {total_distributed}, expected {num_questions}")
        
        # Log the final distribution
        logger.info(f"Final question distribution: {result}")
        
        return result
    
    async def generate_questions(self, 
                               passage: Dict[str, Any], 
                               question_distribution: Dict[str, Dict[str, int]],
                               previous_questions: List[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """
        Generate quiz questions using Claude
        
        Args:
            passage: The passage to generate questions for
            question_distribution: Distribution of questions by standard and difficulty
            previous_questions: List of previously generated questions (to avoid repetition)
            
        Returns:
            List of generated question dictionaries
        """
        if previous_questions is None:
            previous_questions = []
        
        overall_start_time = asyncio.get_event_loop().time()
        total_questions = sum(sum(difficulties.values()) for difficulties in question_distribution.values())
        logger.info(f"Starting generation of {total_questions} questions")
        
        try:
            # Create tasks for each standard and difficulty level
            logger.info("Creating question generation tasks")
            tasks = []
            task_info = []  # Store info about each task for logging
            task_counter = 0
            
            for standard_id, difficulties in question_distribution.items():
                for difficulty_level, count in difficulties.items():
                    logger.debug(f"Preparing {count} tasks for standard {standard_id} at difficulty {difficulty_level}")
                    for i in range(count):
                        task_counter += 1
                        # Find example question for this standard and difficulty
                        difficulty_code = DIFFICULTY_MAP.get(difficulty_level, "1")
                        examples = self.examples_by_standard_and_difficulty.get((standard_id, difficulty_code), [])
                        
                        if not examples:
                            logger.warning(f"No example questions found for {standard_id} at difficulty {difficulty_level}")
                            continue
                        
                        example = random.choice(examples)
                        logger.debug(f"Selected example question for standard {standard_id}, difficulty {difficulty_level}")
                        
                        # Create task
                        task = self.generate_question_for_standard_and_difficulty(
                            passage, 
                            standard_id, 
                            difficulty_level, 
                            example, 
                            previous_questions.copy(),
                            f"Question {task_counter}/{total_questions}"  # Add task identifier
                        )
                        tasks.append(task)
                        task_info.append({
                            "standard": standard_id,
                            "difficulty": difficulty_level,
                            "task_id": task_counter
                        })
            
            logger.info(f"Created {len(tasks)} question generation tasks")
            
            # Process tasks in batches to limit concurrency
            results = []
            for i in range(0, len(tasks), MAX_WORKERS):
                batch_start_time = asyncio.get_event_loop().time()
                batch = tasks[i:i+MAX_WORKERS]
                batch_info = task_info[i:i+MAX_WORKERS]
                
                batch_size = len(batch)
                current_batch = i//MAX_WORKERS + 1
                total_batches = (len(tasks)-1)//MAX_WORKERS + 1
                
                logger.info(f"Processing batch {current_batch}/{total_batches} of {batch_size} questions")
                
                try:
                    # Set a timeout for each batch to prevent hanging
                    batch_timeout = 120  # 2 minutes per batch
                    batch_results = await asyncio.wait_for(
                        asyncio.gather(*batch, return_exceptions=True),
                        timeout=batch_timeout
                    )
                    
                    batch_end_time = asyncio.get_event_loop().time()
                    batch_duration = batch_end_time - batch_start_time
                    
                    # Process results, handling any exceptions
                    successful_questions = 0
                    for result, info in zip(batch_results, batch_info):
                        if isinstance(result, Exception):
                            logger.error(f"Task for standard {info['standard']} at difficulty {info['difficulty']} (Task {info['task_id']}/{total_questions}) failed with error: {str(result)}")
                            continue
                            
                        if result:
                            successful_questions += 1
                            results.append(result)
                            # Add to previous questions to avoid repetition in future tasks
                            previous_questions.append(result)
                        else:
                            logger.warning(f"Failed to generate question for standard {info['standard']} at difficulty {info['difficulty']} (Task {info['task_id']}/{total_questions})")
                    
                    logger.info(f"Batch {current_batch}/{total_batches} complete: {successful_questions}/{batch_size} questions generated successfully in {batch_duration:.2f}s")
                
                except asyncio.TimeoutError:
                    logger.error(f"Batch {current_batch}/{total_batches} timed out after {batch_timeout} seconds")
                except Exception as e:
                    logger.error(f"Error processing batch {current_batch}/{total_batches}: {str(e)}")
            
            overall_end_time = asyncio.get_event_loop().time()
            overall_duration = overall_end_time - overall_start_time
            success_rate = len(results) / total_questions if total_questions > 0 else 0
            
            logger.info(f"Question generation complete: {len(results)}/{total_questions} questions generated successfully ({success_rate:.1%}) in {overall_duration:.2f}s")
            if total_questions > 0:
                logger.info(f"Average time per question: {overall_duration/total_questions:.2f}s")
            
            return results
            
        except Exception as e:
            logger.error(f"Error in generate_questions: {str(e)}")
            # Return any results we managed to get
            return results
            
        except Exception as e:
            logger.error(f"Error in generate_questions: {str(e)}")
            # Return any results we managed to get
            return results

    async def generate_question_for_standard_and_difficulty(self,
                                                         passage: Dict[str, Any],
                                                         standard_id: str,
                                                         difficulty_level: str,
                                                         example_question: Dict[str, Any],
                                                         previous_questions: List[Dict[str, Any]],
                                                         task_id: str = "") -> Dict[str, Any]:
        """
        Generate a single question for a specific standard and difficulty
        
        Args:
            passage: The passage to generate a question for
            standard_id: The standard to target
            difficulty_level: easy, medium, or hard
            example_question: Example question for this standard and difficulty
            previous_questions: List of previously generated questions
            task_id: Identifier for this task (for logging)
            
        Returns:
            Generated question dictionary
        """
        max_attempts = 3
        
        for attempt in range(max_attempts):
            try:
                # Build the prompt to send to Claude
                prompt = build_prompt(
                    passage=passage,
                    standard_id=standard_id, 
                    difficulty_level=difficulty_level,
                    example_question=example_question,
                    previous_questions=previous_questions
                )
                
                # Call Claude
                response = await self.call_claude_with_retry(prompt)
                
                # Parse the response
                question = parse_claude_response(response)
                
                # If parsing failed, try again
                if not question:
                    logger.warning(f"Failed to parse Claude response on attempt {attempt+1}/{max_attempts}")
                    continue
                    
                # Add standard and difficulty to the question
                question["standard"] = standard_id
                question["difficulty"] = difficulty_level
                
                # Skip basic validation and just use quality control
                
                # Advanced quality control check
                validation_result = await self.quality_control.validate_question(
                    question=question,
                    passage=passage,
                    standard_id=standard_id,
                    previous_questions=previous_questions
                )
                
                # Log validation results
                if validation_result.get("warnings", []):
                    for warning in validation_result["warnings"]:
                        logger.warning(f"Question warning: {warning}")
                        
                if validation_result.get("improvement_suggestions", []):
                    for suggestion in validation_result["improvement_suggestions"]:
                        logger.info(f"Improvement suggestion: {suggestion}")
                
                # Check if the question passes all validation checks
                if validation_result["is_valid"]:
                    logger.info(f"Generated valid question for standard {standard_id}, difficulty {difficulty_level}")
                    return question
                else:
                    # Log validation errors
                    for error in validation_result.get("errors", []):
                        logger.warning(f"Question error: {error}")
                    
                    # Try to improve the question
                    logger.info(f"Attempting to improve invalid question (attempt {attempt+1})")
                    improved_question = await self.quality_control.improve_question(
                        question=question,
                        validation_result=validation_result,
                        passage=passage,
                        standard_id=standard_id
                    )
                    
                    if improved_question:
                        # Validate the improved question
                        improved_validation = await self.quality_control.validate_question(
                            question=improved_question,
                            passage=passage,
                            standard_id=standard_id,
                            previous_questions=previous_questions
                        )
                        
                        if improved_validation["is_valid"]:
                            logger.info(f"Successfully improved question for standard {standard_id}")
                            return improved_question
                        else:
                            logger.warning("Improved question still failed validation")
            
            except Exception as e:
                logger.error(f"Error generating question: {str(e)}")
                
        # If all attempts fail, return None or a placeholder
        logger.error(f"Failed to generate valid question after {max_attempts} attempts")
        return None
    
    @with_retry(
    max_retries=config.MAX_RETRIES,
    retry_delay=config.RETRY_DELAY,
    exceptions_to_retry=[
        anthropic.RateLimitError,
        anthropic.APIError,
        anthropic.APIConnectionError,
        ValueError,
        Exception
    ],
    timeout=config.API_TIMEOUT
    )
    async def call_claude_with_retry(self, prompt: str) -> str:
        """
        Call Claude API with retry logic
        
        Args:
            prompt: The prompt to send to Claude
            
        Returns:
            Claude's response
        """
        logger.info("Calling Claude API")
        
        # Initialize client if needed
        if not hasattr(self, 'client') or self.client is None:
            api_key = ANTHROPIC_API_KEY
            if not api_key:
                raise ValueError("No API key provided. Set ANTHROPIC_API_KEY environment variable.")
            self.client = anthropic.Anthropic(api_key=api_key)
            logger.info("Initialized Claude client")
        
        # Make API call using asyncio.to_thread for thread safety
        response = await asyncio.to_thread(
            lambda: self.client.messages.create(
                model=MODEL,
                max_tokens=4096,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
        )
        
        # Check for empty response
        if not response or not response.content or not response.content[0].text:
            raise ValueError("Empty response from Claude API")
        
        return response.content[0].text
    
    def format_quiz_output(self, questions: List[Dict[str, Any]], passage: Dict[str, Any]) -> Dict[str, Any]:
        """
        Format the final quiz output in the required JSON format
        
        Args:
            questions: List of generated questions
            passage: The passage used for the quiz
            
        Returns:
            Formatted quiz data
        """
        return {
            "passage": {
                "id": passage.get("id", ""),
                "title": passage.get("title", ""),
                "author": passage.get("author", ""),
                "type": passage.get("type", ""),
                "text": passage.get("text", "")
            },
            "questions": questions
        }

    def get_timestamp(self) -> str:
        """
        Get the current timestamp in a formatted string
        
        Returns:
            ISO format timestamp string
        """
        return datetime.datetime.now().isoformat(sep=' ', timespec='seconds')

# Helper functions
def build_prompt(passage: Dict[str, Any], 
                standard_id: str, 
                difficulty_level: str, 
                example_question: Dict[str, Any],
                previous_questions: List[Dict[str, Any]]) -> str:
    """
    Build the prompt to send to Claude for question generation
    
    Args:
        passage: The passage to generate a question for
        standard_id: The standard to target
        difficulty_level: easy, medium, or hard
        example_question: Example question for this standard and difficulty
        previous_questions: List of previously generated questions
        
    Returns:
        Formatted prompt string
    """
    # Extract passage info
    passage_title = passage.get("title", "")
    passage_author = passage.get("author", "")
    passage_type = passage.get("type", "")
    passage_text = passage.get("text", "")
    
    # Build a passage description
    passage_description = f"{passage_title}"
    if passage_author:
        passage_description += f" by {passage_author}"
    if passage_type:
        passage_description += f" ({passage_type})"
    
    # Extract question info from example
    example_text = example_question.get("question", "")
    example_answer = example_question.get("correct_answer", "")
    example_distractors = [
        example_question.get("distractor1", ""),
        example_question.get("distractor2", ""),
        example_question.get("distractor3", "")
    ]
    
    # Format previous questions to avoid repetition
    prev_questions_text = ""
    if previous_questions:
        prev_questions_text = "Previously generated questions for this passage:\n\n"
        for i, q in enumerate(previous_questions):
            question_text = q.get("question", "").strip()
            answer_text = q.get("correct_answer", "").strip()
            prev_questions_text += f"{i+1}. {question_text}\n   Answer: {answer_text}\n\n"
    
    # Build the prompt
    prompt = f"""You are an expert assessment designer creating high-quality multiple-choice questions for AP English Language and Composition quizzes.

TASK:
Create a new multiple-choice question based on the following passage. The question should align with the specified educational standard and difficulty level.

PASSAGE TITLE: {passage_description}

PASSAGE:
{passage_text}

EXAMPLE QUESTION FOR THIS STANDARD AND DIFFICULTY:
Question: {example_text}
Correct Answer: {example_answer}
Distractor 1: {example_distractors[0]}
Distractor 2: {example_distractors[1]}
Distractor 3: {example_distractors[2]}

{prev_questions_text}

## Generation Instructions:
1. Create a new question for this passage that:
   - Tests the same skill
   - Uses the same question pattern as the example
   - Is distinctly different from previously generated questions
   - Targets different textual evidence than previous questions

2. Follow these structural requirements:
   - Must use similar language patterns as example
   - Must maintain similar difficulty level
   - Must use parallel answer choice structure
   - Must be provable with direct textual evidence

3. Quality Requirements:
   - Question must be unambiguous
   - Correct answer must be definitively provable
   - Distractors must be plausible but clearly incorrect
   - All options must be distinct from each other
   - No overlap with previous questions' content focus

## Output Format:
```json
{{
  "question": "Your question text here",
  "correct_answer": "The correct answer",
  "distractor1": "First incorrect option",
  "distractor2": "Second incorrect option",
  "distractor3": "Third incorrect option"
}}
```

IMPORTANT INSTRUCTIONS:
- Do not include any line/paragraph number references unless they are in the original passage
- Make sure all distractors are plausible but clearly incorrect when the passage is carefully read
- Do not create questions that are too similar to any previous questions listed
- Do not include any explanation, commentary, or notes - ONLY return the JSON object
- Your response must be valid JSON with no other text before or after it

Your response should ONLY contain the JSON object as specified above.
"""
    return prompt

def parse_claude_response(response: str) -> Dict[str, Any]:
    """
    Parse Claude's response into a structured question format
    
    Args:
        response: Raw response from Claude
        
    Returns:
        Structured question dictionary
    """
    try:
        # First try to find JSON code blocks in the response
        json_pattern = r"```(?:json)?\s*(\{[\s\S]*?\})\s*```"
        json_matches = re.findall(json_pattern, response)
        
        for json_str in json_matches:
            try:
                question_data = json.loads(json_str)
                # Check if it has the expected structure
                required_fields = ["question", "correct_answer", "distractor1", "distractor2", "distractor3"]
                if all(field in question_data for field in required_fields):
                    return question_data
            except json.JSONDecodeError:
                logger.warning("Failed to parse JSON from code block")
                continue
        
        # If no valid JSON in code blocks, try to extract JSON from the full response
        # Find the first { and the last }
        start = response.find('{')
        end = response.rfind('}') + 1
        
        if start >= 0 and end > start:
            json_str = response[start:end]
            try:
                question_data = json.loads(json_str)
                # Check if it has the expected structure
                required_fields = ["question", "correct_answer", "distractor1", "distractor2", "distractor3"]
                if all(field in question_data for field in required_fields):
                    return question_data
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse JSON from response: {json_str[:100]}...")
        
        # If all else fails, try to extract individual fields and construct a dictionary
        question_match = re.search(r'"question"\s*:\s*"([^"]*)"', response)
        answer_match = re.search(r'"correct_answer"\s*:\s*"([^"]*)"', response)
        distractor1_match = re.search(r'"distractor1"\s*:\s*"([^"]*)"', response)
        distractor2_match = re.search(r'"distractor2"\s*:\s*"([^"]*)"', response)
        distractor3_match = re.search(r'"distractor3"\s*:\s*"([^"]*)"', response)
        
        if question_match and answer_match and distractor1_match and distractor2_match and distractor3_match:
            return {
                "question": question_match.group(1),
                "correct_answer": answer_match.group(1),
                "distractor1": distractor1_match.group(1),
                "distractor2": distractor2_match.group(1),
                "distractor3": distractor3_match.group(1)
            }
        
        logger.error("Could not extract question data from Claude's response")
        logger.debug(f"Response content: {response[:200]}...")
        return {}
        
    except Exception as e:
        logger.error(f"Error processing Claude's response: {str(e)}")
        return {}

async def main():
    """
    Main entry point for running the quiz generator
    """
    generator = QuizGenerator()
    # Example usage
    quiz = generator.generate_quiz(lesson_id="lesson1", difficulty=2, num_questions=8)
    print(json.dumps(quiz, indent=2))

if __name__ == "__main__":
    asyncio.run(main()) 