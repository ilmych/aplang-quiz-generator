import json
import os
import re
from typing import Dict, List, Any, Optional
import asyncio
import anthropic
import random

# Import centralized logging
from logging_config import logger

# Import centralized configuration
from config import config

# Import retry decorator
from utils import with_retry

# Load environment variables
from dotenv import load_dotenv

# Configuration from centralized config
MAX_RETRIES = config.MAX_RETRIES
RETRY_DELAY = config.RETRY_DELAY
MODEL = config.MODEL
QC_PROMPTS_FILE = config.QC_PROMPTS_FILE

class QuestionQualityControl:
    """
    A class for ensuring the quality of generated quiz questions using Claude.
    This includes checking for validity, appropriateness, and other quality metrics.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the quality control system.
        
        Args:
            api_key: Optional Anthropic API key (will use environment variable if not provided)
        """
        # Initialize Claude client
        self.api_key = api_key or config.ANTHROPIC_API_KEY
        if not self.api_key:
            logger.warning("No API key provided. QC will attempt to use the API key from main module.")
            
        # Initialize Claude client (will be set in _call_claude_with_retry if not done here)
        self.client = None
        if self.api_key:
            self.client = anthropic.Anthropic(api_key=self.api_key)
            key_preview = f"{self.api_key[:4]}...{self.api_key[-4:]}" if len(self.api_key) > 8 else "Invalid Key"
            logger.info(f"Quality control initialized with API key: {key_preview}")
        
        self.qc_prompts = {}
        self.load_qc_prompts()
    
    def load_qc_prompts(self) -> None:
        """
        Load quality control prompts from the configured file.
        """
        # Check if file exists
        if not os.path.exists(QC_PROMPTS_FILE):
            error_msg = f"Quality control prompts file not found: {QC_PROMPTS_FILE}"
            logger.error(error_msg)
            raise FileNotFoundError(error_msg)
        
        try:
            logger.info(f"Loading quality control prompts from: {QC_PROMPTS_FILE}")
            with open(QC_PROMPTS_FILE, "r", encoding="utf-8") as f:
                prompts_array = json.load(f)
                
                # Convert array of prompt objects to a dictionary keyed by name
                self.qc_prompts = {}
                for prompt_obj in prompts_array:
                    name = prompt_obj.get("name", "")
                    prompt = prompt_obj.get("prompt", "")
                    
                    if name and prompt:
                        self.qc_prompts[name] = prompt
                        logger.info(f"Loaded quality control prompt: {name}")
                    else:
                        logger.warning(f"Skipped prompt with missing name or content")
                
                logger.info(f"Successfully loaded {len(self.qc_prompts)} quality control prompts")
                
                # Make sure we have all required prompts
                required_prompts = [
                    "formatting", "plausibility", "single correct answer", 
                    "structure", "depth", "precision", "textual evidence"
                ]
                missing_prompts = [p for p in required_prompts if p not in self.qc_prompts]
                
                if missing_prompts:
                    warning_msg = f"Missing required quality control prompts: {', '.join(missing_prompts)}"
                    logger.warning(warning_msg)
                    # Don't raise an exception, just warn about missing prompts
                
        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON in quality control prompts file: {str(e)}"
            logger.error(error_msg)
            raise ValueError(error_msg)
        except Exception as e:
            error_msg = f"Error loading quality control prompts: {str(e)}"
            logger.error(error_msg)
            raise
    
    async def validate_question(self, 
                               question: Dict[str, Any],
                               passage: Dict[str, Any],
                               standard_id: str,
                               previous_questions: List[Dict[str, Any]] = None,
                               task_id: str = "") -> Dict[str, Any]:
        """
        Validate a generated question using quality control checks
        
        Args:
            question: The question to validate
            passage: The passage used for the question
            standard_id: The standard ID for the question
            previous_questions: Previously generated questions
            task_id: Identifier for this task (for logging)
            
        Returns:
            Validation result dictionary with all validation info
        """
        start_time = asyncio.get_event_loop().time()
        logger.info(f"{task_id}: Starting question validation for standard {standard_id}")
        
        if previous_questions is None:
            previous_questions = []
                
        # Initialize result dictionary
        result = {
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "improvement_suggestions": [],
            "quality_checks": {}
        }
        
        # Skip basic validation - just go directly to advanced validation
        # Step 2: Advanced validation
        advanced_validation_start = asyncio.get_event_loop().time()
        logger.debug(f"{task_id}: Starting advanced validation")
        
        advanced_result = await self._perform_advanced_validation(
            question, passage, standard_id, previous_questions, task_id
        )
        advanced_validation_time = asyncio.get_event_loop().time() - advanced_validation_start
        logger.debug(f"{task_id}: Advanced validation completed in {advanced_validation_time:.2f}s")
        
        # Merge advanced validation results
        for key in advanced_result:
            if key in result:
                if isinstance(result[key], list) and isinstance(advanced_result[key], list):
                    result[key].extend(advanced_result[key])
                elif isinstance(result[key], bool) and isinstance(advanced_result[key], bool):
                    result[key] = result[key] and advanced_result[key]
                else:
                    result[key] = advanced_result[key]
            else:
                result[key] = advanced_result[key]
        
        # Log validation success or failure
        end_time = asyncio.get_event_loop().time()
        total_time = end_time - start_time
        
        validation_status = "passed" if result["is_valid"] else "failed"
        
        if result["is_valid"]:
            logger.info(f"{task_id}: Question validation {validation_status} in {total_time:.2f}s")
        else:
            logger.warning(f"{task_id}: Question validation {validation_status} with {len(result['errors'])} errors in {total_time:.2f}s")
                
        return result
    
    def _perform_basic_validation(self, question: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform basic validation checks on the question.
        Note: This validation has been disabled to allow Claude's outputs to be processed directly.
        
        Args:
            question: The question to validate
            
        Returns:
            Dictionary with validation results - always valid
        """
        # Return a valid result without performing any checks
        return {
            "is_valid": True,
            "errors": [],
            "warnings": []
        }
    
    async def _perform_advanced_validation(self, 
                                     question: Dict[str, Any],
                                     passage: Dict[str, Any],
                                     standard_id: str,
                                     previous_questions: List[Dict[str, Any]],
                                     task_id: str = "") -> Dict[str, Any]:
        """
        Perform advanced validation using Claude quality control checks
        
        Args:
            question: The question to validate
            passage: The passage used for the question
            standard_id: The standard ID for the question
            previous_questions: Previously generated questions
            task_id: Identifier for this task (for logging)
            
        Returns:
            Validation result dictionary
        """
        # List of required quality checks
        required_checks = [
            "formatting", 
            "structure", 
            "depth", 
            "precision", 
            "textual evidence", 
            "single correct answer"
        ]
        
        # Initialize result
        result = {
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "improvement_suggestions": [],
            "quality_checks": {}
        }
        
        # Run each required check
        for check_name in required_checks:
            check_start_time = asyncio.get_event_loop().time()
            logger.info(f"{task_id}: Running quality check: {check_name}")
            
            check_result = await self._run_specific_quality_check(
                check_name, question, passage, standard_id, task_id
            )
            
            check_duration = asyncio.get_event_loop().time() - check_start_time
            logger.info(f"{task_id}: {check_name} check completed in {check_duration:.2f}s")
            
            # Log the result
            passes = check_result.get("passes", False)
            score = check_result.get("score", 0)
            reasoning = check_result.get("reasoning", "No reasoning provided")
            
            if passes:
                logger.info(f"{task_id}: Passed {check_name} check, score: {score}")
            else:
                logger.warning(f"{task_id}: Failed {check_name} check, score: {score}, reason: {reasoning}")
                result["errors"].append(f"Failed {check_name} check: {reasoning}")
                
            # Update result
            result["quality_checks"][check_name] = check_result
            
            # If a required check fails, mark the question as invalid
            if not passes:
                result["is_valid"] = False
                if reasoning:
                    result["improvement_suggestions"].append(
                        f"Improve {check_name}: {reasoning}"
                    )
        
        # Run plausibility check separately
        check_start_time = asyncio.get_event_loop().time()
        logger.info(f"{task_id}: Running plausibility checks for distractors")
        
        # Get the difficulty level to determine how many plausible distractors are needed
        difficulty_level = question.get("difficulty", "").lower()
        
        # Default to medium difficulty if not specified
        if difficulty_level not in ["easy", "medium", "hard"]:
            if isinstance(difficulty_level, str) and difficulty_level == "1":
                difficulty_level = "easy"
            elif isinstance(difficulty_level, str) and difficulty_level == "3":
                difficulty_level = "hard"
            else:
                difficulty_level = "medium"
                
        logger.info(f"{task_id}: Question difficulty level: {difficulty_level}")
        
        # Check plausibility for each distractor
        plausibility_results = await self._check_distractor_plausibility(
            question, passage, standard_id, task_id
        )
        
        plausible_distractors = 0
        distractor_results = plausibility_results.get("distractors", [])
        
        # Count plausible distractors
        for distractor_result in distractor_results:
            if distractor_result.get("is_plausible", False):
                plausible_distractors += 1
        
        # Determine how many plausible distractors are required based on difficulty
        if difficulty_level == "easy":
            required_plausible = 1
        else:  # medium or hard
            required_plausible = 2
        
        check_duration = asyncio.get_event_loop().time() - check_start_time
        logger.info(f"{task_id}: Plausibility check completed in {check_duration:.2f}s")
        logger.info(f"{task_id}: Found {plausible_distractors} plausible distractors (need {required_plausible})")
        
        # Set overall plausibility check result
        plausibility_passes = plausible_distractors >= required_plausible
        
        # Add plausibility check result
        result["quality_checks"]["plausibility"] = {
            "passes": plausibility_passes,
            "score": 1 if plausibility_passes else 0,
            "reasoning": f"Found {plausible_distractors} plausible distractors, need {required_plausible} for {difficulty_level} difficulty",
            "distractor_results": distractor_results
        }
        
        if plausibility_passes:
            logger.info(f"{task_id}: Passed plausibility check with {plausible_distractors} plausible distractors")
        else:
            logger.warning(f"{task_id}: Failed plausibility check: only {plausible_distractors} distractors are plausible (need {required_plausible})")
            result["is_valid"] = False
            result["errors"].append(f"Failed plausibility check: Only {plausible_distractors} out of 3 distractors are plausible. {difficulty_level.capitalize()} difficulty questions require at least {required_plausible} plausible distractors.")
            result["improvement_suggestions"].append(f"Improve plausibility: Make at least {required_plausible} distractors plausible for {difficulty_level} difficulty questions.")
        
        return result
    
    def _format_qc_prompt(self, 
                        prompt_template: str,
                        question: Dict[str, Any],
                        passage: Dict[str, Any],
                        standard_id: str,
                        previous_questions: List[Dict[str, Any]]) -> str:
        """
        Format the QC prompt template with the question, passage, and other details.
        
        Args:
            prompt_template: The template string from the QC prompts file
            question: The question to validate
            passage: The passage the question is based on
            standard_id: The educational standard this question targets
            previous_questions: Previously generated questions for this passage
            
        Returns:
            Formatted prompt string
        """
        # Format the question as JSON
        question_json = json.dumps(question, indent=2)
        
        # Format passage information
        passage_info = f"{passage.get('title', 'Untitled')} by {passage.get('author', 'Unknown')} ({passage.get('type', 'Unknown')})"
        passage_text = passage.get('text', '')
        
        # Format previous questions
        prev_questions_text = ""
        if previous_questions:
            prev_questions_text = "Previous questions for this passage:\n\n"
            for i, q in enumerate(previous_questions, 1):
                prev_questions_text += f"{i}. {q.get('question', '')}\n"
                prev_questions_text += f"   Correct answer: {q.get('correct_answer', '')}\n\n"
        
        # Replace placeholders in the template
        formatted_prompt = prompt_template.replace("{QUESTION_JSON}", question_json)
        formatted_prompt = formatted_prompt.replace("{PASSAGE_INFO}", passage_info)
        formatted_prompt = formatted_prompt.replace("{PASSAGE_TEXT}", passage_text)
        formatted_prompt = formatted_prompt.replace("{STANDARD_ID}", standard_id)
        formatted_prompt = formatted_prompt.replace("{PREVIOUS_QUESTIONS}", prev_questions_text)
        
        return formatted_prompt
    
    @with_retry(
        max_retries=MAX_RETRIES,
        retry_delay=RETRY_DELAY,
        exceptions_to_retry=[
            anthropic.RateLimitError,
            anthropic.APIError,
            anthropic.APIConnectionError,
            ValueError,
            Exception
        ],
        timeout=config.API_TIMEOUT
    )
    async def _call_claude_with_retry(self, prompt: str) -> str:
        """
        Call Claude API with retry logic
        
        Args:
            prompt: The prompt to send to Claude
            
        Returns:
            Claude's response
        """
        logger.info("Making Claude API call")
        
        # Initialize client if needed
        if not hasattr(self, 'client') or self.client is None:
            api_key = self.api_key or config.ANTHROPIC_API_KEY
            if not api_key:
                raise ValueError("No API key provided. Set ANTHROPIC_API_KEY environment variable.")
            self.client = anthropic.Anthropic(api_key=api_key)
            logger.info("Initialized Claude client")
        
        # Make API call
        response = await asyncio.to_thread(
            lambda: self.client.messages.create(
                model=MODEL,
                max_tokens=4000,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
        )
        
        # Check if response is valid
        if not response or not response.content or len(response.content) == 0:
            raise ValueError("Empty response from Claude API")
        
        # Extract the response text
        response_text = response.content[0].text
        
        # Check if the response is too short to be valid
        if len(response_text) < 10:
            raise ValueError(f"Response too short: '{response_text}'")
        
        # Valid response received
        return response_text
    
    def _parse_validation_response(self, response: str) -> Dict[str, Any]:
        """
        Parse Claude's validation response.
        
        Args:
            response: Raw response from Claude
            
        Returns:
            Parsed validation results
        """
        result = {
            "is_valid": True,
            "errors": [],
            "warnings": [],
            "improvement_suggestions": []
        }
        
        try:
            # First, try to find JSON in the response
            json_pattern = r"```json\s*([\s\S]*?)\s*```"
            json_matches = re.findall(json_pattern, response)
            if json_matches:
                try:
                    parsed_data = json.loads(json_matches[0])
                    
                    # Extract fields from the parsed JSON
                    result["is_valid"] = parsed_data.get("is_valid", True)
                    result["errors"] = parsed_data.get("errors", [])
                    result["warnings"] = parsed_data.get("warnings", [])
                    result["improvement_suggestions"] = parsed_data.get("improvement_suggestions", [])
                    
                    return result
                except json.JSONDecodeError:
                    logger.warning("Could not parse JSON in QC response")
            
            # If no JSON or invalid JSON, extract information using regex
            # Look for errors
            error_section = re.search(r"(?:Errors|ERRORS):(.*?)(?:\n\n|\n[A-Z]|\Z)", response, re.DOTALL | re.IGNORECASE)
            if error_section:
                errors = [e.strip() for e in error_section.group(1).strip().split("\n-")]
                errors = [e for e in errors if e]
                if errors:
                    result["is_valid"] = False
                    result["errors"] = errors
            
            # Look for warnings
            warning_section = re.search(r"(?:Warnings|WARNINGS):(.*?)(?:\n\n|\n[A-Z]|\Z)", response, re.DOTALL | re.IGNORECASE)
            if warning_section:
                warnings = [w.strip() for w in warning_section.group(1).strip().split("\n-")]
                warnings = [w for w in warnings if w]
                result["warnings"] = warnings
            
            # Look for suggestions
            suggestion_section = re.search(r"(?:Suggestions|SUGGESTIONS|Improvements|IMPROVEMENTS):(.*?)(?:\n\n|\n[A-Z]|\Z)", response, re.DOTALL | re.IGNORECASE)
            if suggestion_section:
                suggestions = [s.strip() for s in suggestion_section.group(1).strip().split("\n-")]
                suggestions = [s for s in suggestions if s]
                result["improvement_suggestions"] = suggestions
            
            # Check for explicit valid/invalid statement
            valid_match = re.search(r"(valid|invalid|pass|fail)", response, re.IGNORECASE)
            if valid_match:
                result["is_valid"] = valid_match.group(1).lower() in ["valid", "pass"]
            
        except Exception as e:
            logger.error(f"Error parsing validation response: {str(e)}")
            result["warnings"].append(f"Could not fully parse validation results: {str(e)}")
        
        return result
    
    async def improve_question(self, 
                             question: Dict[str, Any],
                             validation_result: Dict[str, Any],
                             passage: Dict[str, Any],
                             standard_id: str,
                             task_id: str = "") -> Dict[str, Any]:
        """
        Attempt to improve a question that failed validation
        
        Args:
            question: The original question
            validation_result: The validation result with errors
            passage: The passage used for the question
            standard_id: The standard ID for the question
            task_id: Identifier for this task (for logging)
            
        Returns:
            Improved question or None if improvement failed
        """
        start_time = asyncio.get_event_loop().time()
        logger.info(f"{task_id}: Attempting to improve question")
        
        # Check if we have errors to fix
        if not validation_result.get("errors") and not validation_result.get("improvement_suggestions"):
            logger.info(f"{task_id}: No errors or suggestions found, no improvement needed")
            return question
                
        # Build improvement prompt
        prompt_start = asyncio.get_event_loop().time()
        prompt = self._build_improvement_prompt(
            question, validation_result, passage, standard_id
        )
        prompt_time = asyncio.get_event_loop().time() - prompt_start
        logger.debug(f"{task_id}: Improvement prompt built in {prompt_time:.2f}s")
        
        # Call Claude with the prompt
        api_start = asyncio.get_event_loop().time()
        logger.info(f"{task_id}: Sending improvement prompt to Claude")
        response = await self._call_claude_with_retry(prompt)
        api_time = asyncio.get_event_loop().time() - api_start
        logger.info(f"{task_id}: Received improvement response from Claude in {api_time:.2f}s")
        
        # Extract improved question
        parse_start = asyncio.get_event_loop().time()
        improved_question = self._extract_improved_question(response)
        parse_time = asyncio.get_event_loop().time() - parse_start
        logger.debug(f"{task_id}: Parsed improvement response in {parse_time:.2f}s")
        
        if not improved_question:
            total_time = asyncio.get_event_loop().time() - start_time
            logger.warning(f"{task_id}: Failed to extract improved question after {total_time:.2f}s")
            return None
                
        # Carry over metadata from original question
        improved_question["standard"] = question.get("standard")
        improved_question["difficulty"] = question.get("difficulty")
        
        # Validate the improved question
        validate_start = asyncio.get_event_loop().time()
        logger.info(f"{task_id}: Validating improved question")
        
        improved_validation = await self.validate_question(
            improved_question, passage, standard_id, task_id=f"{task_id} (improved)"
        )
        
        validate_time = asyncio.get_event_loop().time() - validate_start
        logger.info(f"{task_id}: Improved question validation completed in {validate_time:.2f}s")
        
        # Check if validation succeeded
        if improved_validation["is_valid"]:
            total_time = asyncio.get_event_loop().time() - start_time
            logger.info(f"{task_id}: Question successfully improved in {total_time:.2f}s")
            return improved_question
        else:
            error_count = len(improved_validation.get("errors", []))
            total_time = asyncio.get_event_loop().time() - start_time
            logger.warning(f"{task_id}: Improved question failed validation with {error_count} errors after {total_time:.2f}s")
            return None
    
    def _build_improvement_prompt(self, 
                                question: Dict[str, Any],
                                validation_result: Dict[str, Any],
                                passage: Dict[str, Any],
                                standard_id: str) -> str:
        """
        Build a prompt for improving a question based on validation feedback.
        
        Args:
            question: The original question
            validation_result: The validation results with errors and suggestions
            passage: The passage the question is based on
            standard_id: The educational standard this question targets
            
        Returns:
            Prompt for question improvement
        """
        # Format the question as JSON
        question_json = json.dumps(question, indent=2)
        
        # Format errors, warnings, and suggestions
        errors = "\n".join([f"- {error}" for error in validation_result["errors"]])
        warnings = "\n".join([f"- {warning}" for warning in validation_result["warnings"]])
        suggestions = "\n".join([f"- {suggestion}" for suggestion in validation_result["improvement_suggestions"]])
        
        # Format passage information
        passage_info = f"{passage.get('title', 'Untitled')} by {passage.get('author', 'Unknown')} ({passage.get('type', 'Unknown')})"
        passage_text = passage.get('text', '')
        
        # Build the improvement prompt
        prompt = f"""You are an expert in educational assessment. You need to improve a quiz question based on the validation feedback.

PASSAGE INFORMATION:
{passage_info}

PASSAGE TEXT:
{passage_text}

STANDARD:
{standard_id}

ORIGINAL QUESTION:
{question_json}

VALIDATION FEEDBACK:
"""

        if errors:
            prompt += f"\nERRORS:\n{errors}\n"
        if warnings:
            prompt += f"\nWARNINGS:\n{warnings}\n"
        if suggestions:
            prompt += f"\nIMPROVEMENT SUGGESTIONS:\n{suggestions}\n"

        prompt += """
INSTRUCTIONS:
1. Create an improved version of the question that addresses all the errors and warnings
2. Apply the improvement suggestions
3. Ensure the improved question is still based on the same passage and tests the same standard
4. Maintain the same general structure and difficulty level
5. Return ONLY a valid JSON object with the improved question, using this exact format:

```json
{
  "question": "Your improved question text here?",
  "correct_answer": "The improved correct answer",
  "distractor1": "Improved first incorrect option",
  "distractor2": "Improved second incorrect option",
  "distractor3": "Improved third incorrect option"
}
```

Return ONLY the JSON with no additional text before or after it.
"""
        return prompt
    
    def _extract_improved_question(self, response: str) -> Optional[Dict[str, Any]]:
        """
        Extract the improved question from Claude's response.
        
        Args:
            response: Raw response from Claude
            
        Returns:
            Extracted question dict or None if extraction failed
        """
        try:
            # First, look for a JSON code block
            json_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
            json_matches = re.findall(json_pattern, response)
            
            if json_matches:
                for match in json_matches:
                    try:
                        return json.loads(match)
                    except json.JSONDecodeError:
                        continue
            
            # If no valid JSON in code blocks, try to extract JSON from the full response
            # Find the first { and the last }
            start = response.find('{')
            end = response.rfind('}') + 1
            
            if start >= 0 and end > start:
                json_str = response[start:end]
                try:
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    pass
            
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
            
            return None
                
        except Exception as e:
            logger.error(f"Error extracting improved question: {str(e)}")
            return None
    
    async def _check_distractor_plausibility(self,
                                          question: Dict[str, Any],
                                          passage: Dict[str, Any],
                                          standard_id: str,
                                          task_id: str = "") -> Dict[str, Any]:
        """
        Check the plausibility of each distractor in the question
        
        Args:
            question: The question to check
            passage: The passage used for the question
            standard_id: The standard ID for the question
            task_id: Identifier for this task (for logging)
            
        Returns:
            Plausibility check results
        """
        prompt_template = self.qc_prompts.get("plausibility")
        
        if not prompt_template:
            logger.warning(f"{task_id}: No prompt found for plausibility check")
            return {
                "distractors": [
                    {"id": "distractor1", "is_plausible": False, "reasoning": "No prompt available for plausibility check"},
                    {"id": "distractor2", "is_plausible": False, "reasoning": "No prompt available for plausibility check"},
                    {"id": "distractor3", "is_plausible": False, "reasoning": "No prompt available for plausibility check"}
                ]
            }
            
        # Check each distractor
        logger.info(f"{task_id}: Checking plausibility for 3 distractors")
        distractor_results = []
        plausible_count = 0
        
        distractor_ids = ["distractor1", "distractor2", "distractor3"]
        for distractor_id in distractor_ids:
            distractor_text = question.get(distractor_id, "")
            if not distractor_text:
                logger.warning(f"{task_id}: Missing distractor: {distractor_id}")
                distractor_results.append({
                    "id": distractor_id,
                    "is_plausible": False,
                    "reasoning": "Missing distractor text"
                })
                continue
                
            # Format prompt for this distractor
            start_time = asyncio.get_event_loop().time()
            logger.debug(f"{task_id}: Checking plausibility for {distractor_id}")
            
            prompt = self._format_plausibility_prompt(
                prompt_template, question, passage, standard_id, distractor_id, distractor_text
            )
                
            # Call Claude with the prompt
            response = await self._call_claude_with_retry(prompt)
            
            # Parse response to get plausibility result
            plausibility_result = self._parse_plausibility_response(response)
            
            # Extract score and reasoning
            score = plausibility_result.get("score", 0)
            reasoning = plausibility_result.get("reasoning", "No reasoning provided")
            
            # Determine if plausible
            try:
                is_plausible = int(score) >= 1
            except (ValueError, TypeError):
                is_plausible = False
                
            if is_plausible:
                plausible_count += 1
                
            # Add result for this distractor
            distractor_results.append({
                "id": distractor_id,
                "is_plausible": is_plausible,
                "reasoning": reasoning
            })
            
            time_taken = asyncio.get_event_loop().time() - start_time
            plausibility_status = "plausible" if is_plausible else "not plausible"
            logger.info(f"{task_id}: {distractor_id} is {plausibility_status} (checked in {time_taken:.2f}s)")
            
        logger.info(f"{task_id}: Found {plausible_count} plausible distractors out of 3")
        
        return {
            "distractors": distractor_results
        }
    
    def _format_plausibility_prompt(self,
                                 prompt_template: str,
                                 question: Dict[str, Any],
                                 passage: Dict[str, Any],
                                 standard_id: str,
                                 distractor_id: str,
                                 distractor_text: str) -> str:
        """
        Format the plausibility check prompt for a specific distractor.
        
        Args:
            prompt_template: The plausibility prompt template
            question: The question being validated
            passage: The passage the question is based on
            standard_id: The educational standard
            distractor_id: The ID of the distractor (distractor1, distractor2, etc.)
            distractor_text: The text of the distractor
            
        Returns:
            Formatted prompt for plausibility check
        """
        # Create input JSON for the prompt
        input_json = {
            "passage": passage.get("text", ""),
            "passage_info": f"{passage.get('title', 'Untitled')} by {passage.get('author', 'Unknown')} ({passage.get('type', 'Unknown')})",
            "question": question.get("question", ""),
            "correct_answer": question.get("correct_answer", ""),
            "distractor_to_check": distractor_text,
            "standard_id": standard_id
        }
        
        # Replace the special placeholder with properly formatted JSON
        json_str = json.dumps(input_json, indent=2)
        formatted_prompt = prompt_template.replace("{json.dumps(input_json, indent=2)}", json_str)
        
        # Also handle any other standard placeholders that might be in the template
        formatted_prompt = formatted_prompt.replace("{passage}", passage.get("text", ""))
        formatted_prompt = formatted_prompt.replace("{PASSAGE_TEXT}", passage.get("text", ""))
        formatted_prompt = formatted_prompt.replace("{question}", question.get("question", ""))
        formatted_prompt = formatted_prompt.replace("{QUESTION}", question.get("question", ""))
        formatted_prompt = formatted_prompt.replace("{correct_answer}", question.get("correct_answer", ""))
        formatted_prompt = formatted_prompt.replace("{distractor_to_check}", distractor_text)
        formatted_prompt = formatted_prompt.replace("{STANDARD_ID}", standard_id)
        
        return formatted_prompt
    
    def _parse_plausibility_response(self, response: str) -> Dict[str, Any]:
        """
        Parse Claude's response for distractor plausibility.
        
        Args:
            response: Raw response from Claude
            
        Returns:
            Dictionary with plausibility check results
        """
        result = {
            "is_plausible": False,
            "reasoning": ""
        }
        
        try:
            # Look for JSON in answer tags - this is the expected format
            answer_pattern = r"<answer>([\s\S]*?)</answer>"
            answer_match = re.search(answer_pattern, response)
            
            if answer_match:
                answer_text = answer_match.group(1).strip()
                try:
                    # Try to parse as JSON
                    answer_data = json.loads(answer_text)
                    # The score field is expected to be 0 or 1
                    score = answer_data.get("score", 0)
                    result["is_plausible"] = score == 1
                    result["reasoning"] = answer_data.get("reasoning", "")
                    return result
                except json.JSONDecodeError:
                    logger.warning("Failed to parse JSON from answer tags for plausibility check")
            
            # If no answer tags or JSON parsing failed, try to find JSON block
            json_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
            json_matches = re.findall(json_pattern, response)
            
            for json_str in json_matches:
                try:
                    answer_data = json.loads(json_str)
                    score = answer_data.get("score", 0)
                    result["is_plausible"] = score == 1
                    result["reasoning"] = answer_data.get("reasoning", "")
                    return result
                except json.JSONDecodeError:
                    continue
            
            # Try to find score using regex
            score_pattern = r"\"score\":\s*(\d+)"
            score_match = re.search(score_pattern, response)
            
            if score_match:
                score = int(score_match.group(1))
                result["is_plausible"] = score == 1
            
            # Try to find reasoning
            reasoning_pattern = r"\"reasoning\":\s*\"([^\"]*)\""
            reasoning_match = re.search(reasoning_pattern, response)
            
            if reasoning_match:
                result["reasoning"] = reasoning_match.group(1)
            
            # Look for explicit plausibility mentions
            if "plausible" in response.lower():
                plausible_context = re.search(r"[^\.\n]*plausible[^\.\n]*", response.lower())
                if plausible_context and plausible_context.group(0):
                    context = plausible_context.group(0)
                    if any(neg in context for neg in ["not plausible", "implausible", "isn't plausible", "is not plausible"]):
                        result["is_plausible"] = False
                    else:
                        result["is_plausible"] = True
                        
        except Exception as e:
            logger.error(f"Error parsing plausibility response: {str(e)}")
        
        return result
    
    async def _run_specific_quality_check(self,
                                        check_name: str,
                                        question: Dict[str, Any],
                                        passage: Dict[str, Any],
                                        standard_id: str,
                                        task_id: str = "") -> Dict[str, Any]:
        """
        Run a specific quality check on the question
        
        Args:
            check_name: Name of the quality check to run
            question: The question to validate
            passage: The passage used for the question
            standard_id: The standard ID for the question
            task_id: Identifier for this task (for logging)
            
        Returns:
            Quality check result
        """
        # Get prompt template for this check
        prompt_template = self.qc_prompts.get(check_name)
        
        if not prompt_template:
            logger.warning(f"{task_id}: No prompt found for quality check: {check_name}")
            return {
                "passes": False,
                "score": 0,
                "reasoning": f"No prompt available for {check_name} check"
            }
            
        # Format prompt with question details
        prompt = self._format_quality_check_prompt(
            prompt_template, question, passage, standard_id
        )
            
        # Call Claude with the prompt
        start_time = asyncio.get_event_loop().time()
        logger.debug(f"{task_id}: Sending {check_name} quality check prompt to Claude")
        response = await self._call_claude_with_retry(prompt)
        api_time = asyncio.get_event_loop().time() - start_time
        logger.debug(f"{task_id}: Received {check_name} quality check response from Claude in {api_time:.2f}s")
        
        # Parse response to get check result
        check_result = self._parse_quality_check_response(response)
        
        # Ensure score is valid, convert to pass/fail
        score = check_result.get("score", 0)
        if not isinstance(score, (int, float)):
            try:
                score = int(score)
            except (ValueError, TypeError):
                score = 0
                
        passes = score >= 1
        
        # Return result with pass/fail status
        return {
            "passes": passes,
            "score": score,
            "reasoning": check_result.get("reasoning", "")
        }
    
    def _format_quality_check_prompt(self,
                                  prompt_template: str,
                                  question: Dict[str, Any],
                                  passage: Dict[str, Any],
                                  standard_id: str) -> str:
        """
        Format a quality check prompt.
        
        Args:
            prompt_template: The prompt template
            question: The question to validate
            passage: The passage the question is based on
            standard_id: The educational standard
            
        Returns:
            Formatted prompt for the quality check
        """
        # Replace placeholders in the template
        formatted_prompt = prompt_template
        
        # Replace passage info - different formats are used in different prompts
        passage_text = passage.get("text", "")
        passage_info = f"{passage.get('title', 'Untitled')} by {passage.get('author', 'Unknown')} ({passage.get('type', 'Unknown')})"
        
        # Replace various passage placeholders
        formatted_prompt = formatted_prompt.replace("{passage}", passage_text)
        formatted_prompt = formatted_prompt.replace("{PASSAGE_TEXT}", passage_text)
        formatted_prompt = formatted_prompt.replace("{PASSAGE_INFO}", passage_info)
        
        # Replace question and answer info - check for different formats used in the prompts
        question_text = question.get("question", "")
        correct_answer = question.get("correct_answer", "")
        distractor1 = question.get("distractor1", "")
        distractor2 = question.get("distractor2", "")
        distractor3 = question.get("distractor3", "")
        
        # Replace question and answer placeholders
        formatted_prompt = formatted_prompt.replace("{question}", question_text)
        formatted_prompt = formatted_prompt.replace("{QUESTION}", question_text)
        formatted_prompt = formatted_prompt.replace("{correct_answer}", correct_answer)
        formatted_prompt = formatted_prompt.replace("{distractor1}", distractor1)
        formatted_prompt = formatted_prompt.replace("{distractor2}", distractor2)
        formatted_prompt = formatted_prompt.replace("{distractor3}", distractor3)
        
        # Replace standard ID if used
        formatted_prompt = formatted_prompt.replace("{STANDARD_ID}", standard_id)
        
        return formatted_prompt
    
    def _parse_quality_check_response(self, response: str) -> Dict[str, Any]:
        """
        Parse Claude's response for a quality check.
        
        Args:
            response: Raw response from Claude
            
        Returns:
            Dictionary with check results
        """
        result = {
            "score": 0,
            "reasoning": "",
            "details": response
        }
        
        try:
            # First try to find JSON in answer tags - this is the expected format
            answer_pattern = r"<answer>([\s\S]*?)</answer>"
            answer_match = re.search(answer_pattern, response)
            
            if answer_match:
                answer_text = answer_match.group(1).strip()
                try:
                    # Try to parse as JSON
                    answer_data = json.loads(answer_text)
                    # The score field is expected to be 0 or 1
                    result["score"] = answer_data.get("score", 0)
                    result["reasoning"] = answer_data.get("reasoning", "")
                    return result
                except json.JSONDecodeError:
                    logger.warning("Failed to parse JSON from answer tags")
            
            # If no answer tags or JSON parsing failed, try to find JSON block
            json_pattern = r"```(?:json)?\s*([\s\S]*?)\s*```"
            json_matches = re.findall(json_pattern, response)
            
            for json_str in json_matches:
                try:
                    answer_data = json.loads(json_str)
                    result["score"] = answer_data.get("score", 0)
                    result["reasoning"] = answer_data.get("reasoning", "")
                    return result
                except json.JSONDecodeError:
                    continue
            
            # Try to find score using regex
            score_pattern = r"\"score\":\s*(\d+)"
            score_match = re.search(score_pattern, response)
            
            if score_match:
                result["score"] = int(score_match.group(1))
            
            # Try to find reasoning
            reasoning_pattern = r"\"reasoning\":\s*\"([^\"]*)\""
            reasoning_match = re.search(reasoning_pattern, response)
            
            if reasoning_match:
                result["reasoning"] = reasoning_match.group(1)
            
            # Look for explicit pass/fail mentions
            if "pass" in response.lower() or "fail" in response.lower():
                # If both are present, look for the one closer to "score"
                if "pass" in response.lower() and "fail" in response.lower():
                    pass_index = response.lower().find("pass")
                    fail_index = response.lower().find("fail")
                    score_index = response.lower().find("score")
                    
                    # Use the one closer to "score"
                    if score_index >= 0 and pass_index >= 0 and fail_index >= 0:
                        if abs(pass_index - score_index) < abs(fail_index - score_index):
                            result["score"] = 1
                        else:
                            result["score"] = 0
                else:
                    # Just one is present
                    result["score"] = 1 if "pass" in response.lower() and "fail" not in response.lower() else 0
                    
        except Exception as e:
            logger.error(f"Error parsing quality check response: {str(e)}")
        
        return result

# Usage example
async def test_quality_control():
    # Sample question and passage
    question = {
        "question": "What rhetorical device does the author primarily use in the first paragraph?",
        "correct_answer": "Metaphor",
        "distractor1": "Simile",
        "distractor2": "Alliteration",
        "distractor3": "Hyperbole"
    }
    
    passage = {
        "id": "1",
        "title": "Letter from Birmingham Jail",
        "author": "Martin Luther King Jr.",
        "type": "Letter",
        "text": "But when you have seen vicious mobs lynch your mothers and fathers at will and drown your sisters and brothers at whim...",
        "standards": ["RHS-1.A", "RHS-1.B"]
    }
    
    # Initialize quality control
    qc = QuestionQualityControl()
    
    # Validate the question
    validation_result = await qc.validate_question(question, passage, "RHS-1.A")
    print("Validation result:", validation_result)
    
    # Try to improve the question if needed
    if not validation_result["is_valid"] or validation_result["warnings"] or validation_result["improvement_suggestions"]:
        improved_question = await qc.improve_question(question, validation_result, passage, "RHS-1.A")
        print("Improved question:", improved_question)

if __name__ == "__main__":
    asyncio.run(test_quality_control())
