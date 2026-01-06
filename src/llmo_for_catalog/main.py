#!/usr/bin/env python
import sys
import warnings
from pathlib import Path
from datetime import datetime, timezone

from llmo_for_catalog.crew import LlmoForCatalog

warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")


def run():
    """
    Run the crew.
    """
    inputs = {
        "pdp_url": "https://www.adobestore.com/products/p-adb366/adb366"
    }

    try:

        result = LlmoForCatalog().crew().kickoff(inputs=inputs)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_file = Path(f"test_result_{timestamp}.txt")

        # Some CrewAI result objects have `.raw`, others stringify nicely
        content = getattr(result, "raw", None)
        if content is None:
            content = str(result)

        out_file.write_text(content, encoding="utf-8")
        print(f"Report saved to {out_file}")

    except Exception as e:
        raise Exception(f"An error occurred while running the crew run: {e}")


def train():
    """
    Train the crew for a given number of iterations.
    """
    inputs = {
        "pdp_url": "https://www.adobestore.com/products/p-adb366/adb366"
    }
    try:
        LlmoForCatalog().crew().train(n_iterations=int(sys.argv[1]), filename=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")

def replay():
    """
    Replay the crew execution from a specific task.
    """
    try:
        LlmoForCatalog().crew().replay(task_id=sys.argv[1])

    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")

def test():
    """
    Test the crew execution and returns the results.
    """
    inputs = {
        "topic": "AI LLMs",
        "current_year": str(datetime.now().year)
    }
    
    try:
        LlmoForCatalog().crew().test(n_iterations=int(sys.argv[1]), eval_llm=sys.argv[2], inputs=inputs)

    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")