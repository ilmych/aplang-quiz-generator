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

    args = parser.parse_args()
    
    # Validate arguments - require lesson or standard if not listing
    if not (args.list_lessons or args.list_standards) and not (args.lesson or args.standard):
        parser.error("One of --lesson or --standard is required when not using list operations")
        
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

async def main():
    """Main entry point for the CLI."""
    args = parse_args()

    # Set log level based on verbosity
    if args.verbose:
        configure_logging(logging.DEBUG)

    # Set API key if provided
    if args.api_key:
        os.environ["ANTHROPIC_API_KEY"] = args.api_key
        logger.info("Using API key from command line")

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
        
        # Save the output
        output_file = save_output(quiz, args.output_file)
        num_questions_generated = quiz.get("metadata", {}).get("num_questions_generated", 0)
        logger.info(f"Quiz generated with {num_questions_generated} questions")
        logger.info(f"Saved to: {output_file}")

        # Print a summary
        passage_title = quiz.get("passage", {}).get("title", "Unknown title")
        passage_author = quiz.get("passage", {}).get("author", "Unknown author")
        print(f"\nGenerated quiz on: {passage_title} by {passage_author}")
        print(f"Total questions: {num_questions_generated}")
        print(f"Output saved to: {output_file}")

    except KeyboardInterrupt:
        logger.info("Quiz generation cancelled by user")
        sys.exit(130)  # Standard exit code for SIGINT
    except Exception as e:
        logger.error(f"Failed to generate quiz: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main()) 