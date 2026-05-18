import re

def clean_model_output(text: str) -> str:
    """
    Cleans reasoning-distilled model output by removing the 'Thinking Process' block.
    Matches everything between 'Thinking' and '...done thinking.'
    """
    # Regex to remove 'Thinking... thinking process ... ...done thinking.' case-insensitively
    pattern = re.compile(r'Thinking.*?process.*?\.\.\.done thinking\.', re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(pattern, '', text)
    
    # Also handle simpler 'Thought process' or '<thought>' blocks if needed
    cleaned = re.sub(r'<thought>.*?</thought>', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    
    return cleaned.strip()

if __name__ == "__main__":
    test_text = """
    Thinking...
    Thinking Process:
    1. Decide to say hello.
    ...done thinking.
    
    Hello, world!
    """
    print(f"Cleaned output: '{clean_model_output(test_text)}'")
