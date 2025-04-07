# Quiz Generator System

This system generates educational quizzes using Claude's Sonnet 3.7 model. It creates multiple-choice questions based on reading passages, aligned to educational standards and difficulty levels.

## Features

- Generate quizzes with customizable number of questions (6-12)
- Three difficulty levels with appropriate question distribution
- Questions based on educational standards
- Automatic passage selection relevant to standards
- Asynchronous processing for efficient question generation
- Advanced quality control with AI validation and improvement
- Centralized configuration and logging
- Robust retry logic with exponential backoff
- Graceful fallback mechanisms for handling missing data
- Question validation to ensure quality
- Command-line interface for easy usage
- Optional quiz publishing to PowerPath

## Prerequisites

- Python 3.8+
- Anthropic API key for Claude access

## Data Files

The system uses four primary JSON data files:

1. **lang_lessons.json**: Contains the lessons and their associated standards
2. **lang_passages.json**: Library of reading passages with their associated standards
3. **lang_examples.json**: Example questions for each standard and difficulty level
4. **lang-question-qc.json**: Quality control prompts for different types of standards

### Passage Format with Standards

The `lang_passages.json` file should include a standards array for each passage, like this:

```json
[
  {
    "id": "1",
    "title": "Letter from Birmingham Jail",
    "author": "Martin Luther King Jr.",
    "type": "Letter",
    "text": "<p>The full text of the passage...</p>",
    "standards": ["RHS-1.A", "RHS-1.B", "CLE-2.A"]
  },
  {
    "id": "2",
    "title": "The Great Gatsby",
    "author": "F. Scott Fitzgerald",
    "type": "Novel",
    "text": "<p>The full text of the passage...</p>",
    "standards": ["RL-1.A", "RL-2.B"]
  }
]
```

Each passage can be mapped to multiple standards, and each standard can have multiple passages.

### Quality Control Configuration

The `lang-question-qc.json` file defines validation prompts for different aspects of question quality:

- **formatting**: Ensures proper formatting of questions and options
- **plausibility**: Checks that distractors are plausible but incorrect
- **single correct answer**: Verifies there is exactly one definitive correct answer
- **structure**: Evaluates the structure and balance of answer options
- **depth**: Ensures questions require appropriate analytical thinking
- **precision**: Checks that questions are clearly worded
- **textual evidence**: Verifies questions can be answered from the passage

Each prompt is used by the quality control system to validate generated questions and ensure they meet educational standards.

## Installation

1. Clone the repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Set up your Anthropic API key:
   ```
   export ANTHROPIC_API_KEY=your_key_here
   ```

## Configuration

The system uses a centralized configuration module (`config.py`) that loads settings from environment variables with sensible defaults. You can configure:

- API settings (API key, model, timeouts)
- Retry logic (max retries, delay)
- Concurrency settings (max workers)
- File paths
- Difficulty settings
- Publishing endpoint (optional)

Environment variables that can be set:
- `ANTHROPIC_API_KEY`: Your Anthropic API key
- `ANTHROPIC_MODEL`: Model to use (default: claude-3-7-sonnet-20250219)
- `MAX_RETRIES`: Maximum number of API retries (default: 5)
- `RETRY_DELAY`: Initial delay between retries in seconds (default: 2.0)
- `API_TIMEOUT`: Timeout for API calls in seconds (default: 60)
- `BATCH_TIMEOUT`: Timeout for batch processing in seconds (default: 120)
- `MAX_WORKERS`: Maximum number of concurrent workers (default: 5)
- `DATA_DIR`: Directory containing data files (default: current directory)
- `LOG_LEVEL`: Logging level (default: INFO)
- `INCEPTSTORE_API_URL`: API endpoint for publishing quizzes (default: "https://coreapi.inceptstore.com/case/publish")
- `OUTPUT_DIR`: Directory for saving generated quizzes (default: "generated_quizzes")

## Usage

### Command-Line Interface

The easiest way to use the quiz generator is through the CLI:

```bash
# List available lessons
python cli.py --list-lessons

# List available standards
python cli.py --list-standards

# Generate a quiz for a specific lesson
python cli.py --lesson "Elements of the Rhetorical Situation" --difficulty 2 --num-questions 8

# Generate a quiz for a specific standard
python cli.py --standard "RHS-1.A" --difficulty 3 --num-questions 10 --output-file my_quiz.json

# Set API key from command line
python cli.py --lesson "Exigence" --api-key "your_api_key_here"

# Enable verbose logging
python cli.py --lesson "Claims" --verbose
```

### Python API

You can also use the quiz generator as a Python library. Note that the API is now fully asynchronous:

```python
import asyncio
from main import QuizGenerator

async def generate_sample_quiz():
    generator = QuizGenerator()
    
    # Generate a quiz for a specific lesson
    quiz = await generator.generate_quiz(
        lesson_name="Elements of the Rhetorical Situation",  # Lesson name
        difficulty=2,  # 1 (easy), 2 (medium), or 3 (hard)
        num_questions=8  # Number of questions to generate
    )
    
    # Alternatively, generate a quiz for a specific standard
    # quiz = await generator.generate_quiz(
    #     standard_id="RHS-1.A",
    #     difficulty=2,
    #     num_questions=8
    # )
    
    return quiz

if __name__ == "__main__":
    quiz = asyncio.run(generate_sample_quiz())
    print(quiz)
```

### Publishing Quizzes

The system includes functionality to publish generated quizzes to an external database. This allows the quizzes to be used in educational platforms.

#### Publishing Options

Quizzes can be published in three ways:
1. Create a new course with the quiz
2. Add a quiz to an existing course as a new module
3. Update an existing module in an existing course

#### CLI Publishing Examples

```bash
# Generate a quiz and publish it (interactive mode)
python cli.py --lesson "Audience" --difficulty 2 --num-questions 6 --publish

# Generate a quiz and create a new course automatically
python cli.py --lesson "Claims" --publish --new-course --module-name "Rhetoric Module" --item-name "Claims Quiz" --xp-value 25

# Publish an existing quiz file to a new course
python cli.py --publish-only path/to/quiz.json --new-course --module-name "Module Name" --item-name "Quiz Name" --xp-value 20

# Add a quiz to an existing course
python cli.py --lesson "Audience" --publish --existing-course "course_id_123" --module-name "New Module" --item-name "Audience Quiz" --xp-value 20

# Update an existing module
python cli.py --lesson "Thesis Statement" --publish --update-module "course_id_123:module_id_456" --item-name "Updated Quiz" --xp-value 15
```

#### Using the Publishing Tool Directly

For more direct access to publishing functionality, you can use the standalone publishing tool:

```bash
python publish_quiz_file.py path/to/quiz.json --course-name "Course Name" --module-name "Module Name" --item-name "Item Name" --xp 25
```

## Question Distribution

The system automatically determines the distribution of questions based on:

1. **Difficulty Level**:
   - Level 1 (Easy): 2-5 easy, 2-5 medium, 1-2 hard questions
   - Level 2 (Medium): 2-3 easy, 2-5 medium, 2-4 hard questions
   - Level 3 (Hard): 1-2 easy, 2-4 medium, 2-6 hard questions

2. **Standards Coverage**:
   - Minimum of 3 questions from the lesson standard
   - If a lesson covers multiple standards, minimum of 2 questions per standard
   - Remaining questions from earlier standards in the curriculum
   - No repetition within the quiz

## Quality Control System

The quiz generator includes a sophisticated quality control system that:

1. **Advanced Validation**: Uses Claude to evaluate questions based on standard-specific criteria
2. **Automatic Improvement**: Attempts to fix invalid questions based on validation feedback
3. **Logging**: Records validation results and improvement suggestions

The system is tailored to different standard types, with specific validation criteria for:
- Literature analysis (RL standards)
- Informational text analysis (RI standards) 
- Rhetorical analysis (RHS standards)
- Claims and evidence analysis (CLE standards)

## Advanced Features

### Asynchronous Processing

The system uses asyncio for efficient processing of multiple questions in parallel:
- Batched processing of question generation
- Proper timeout handling for long-running operations
- Controlled concurrency to prevent overwhelming the API

### Retry Logic with Exponential Backoff

The system includes a robust retry mechanism for API calls:
- Exponential backoff with jitter to prevent thundering herd problems
- Configurable retry counts and delays
- Comprehensive error handling for different types of API errors

### Graceful Degradation

The system includes mechanisms to handle errors gracefully:
- Fallback options when requested data is missing
- Partial quiz generation when some questions fail
- Clear error messages in the output

### Centralized Logging

The system uses a centralized logging configuration:
- Consistent log format across all modules
- Configurable log levels
- File and console logging

## Output Format

The system generates quizzes in JSON format:

```json
{
  "passage": {
    "id": "1",
    "title": "Title of the passage",
    "author": "Author Name",
    "type": "Essay",
    "text": "<p>Passage text in HTML format...</p>"
  },
  "questions": [
    {
      "question": "Question text?",
      "correct_answer": "The correct answer",
      "distractor1": "First incorrect option",
      "distractor2": "Second incorrect option",
      "distractor3": "Third incorrect option",
      "standard": "RHS-1.A",
      "difficulty": "2"
    }
  ],
  "metadata": {
    "lesson_name": "Lesson Name",
    "standard_id": "RHS-1.A",
    "difficulty": 2,
    "num_questions": 8,
    "num_questions_generated": 8,
    "timestamp": "2023-06-15 14:30:45"
  }
}
```

## Extending the System

The system is designed to be extensible:

1. **Add more passages**: Add new passages to the `lang_passages.json` file, including the standards field with appropriate standard IDs.
2. **Add more standards**: Add new standards to the `lang_lessons.json` file.
3. **Customize prompts**: Modify the `build_prompt` function to adjust how questions are generated.
4. **Improve validation**: Enhance the validation criteria in the `lang-question-qc.json` file.
5. **Configure behavior**: Adjust settings in the `config.py` file or set environment variables.

## Troubleshooting

- **API Key Issues**: Make sure your Anthropic API key is set correctly.
- **Missing Data**: Check that all four JSON files are present and correctly formatted.
- **Async Issues**: Make sure you're properly awaiting async functions.
- **Timeouts**: Adjust timeout settings in the config if operations are taking too long.
