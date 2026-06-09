from config import DIFFICULTY
from chain import Blockchain

class DifficultyPolicy:
    """Interface class for difficulty policies. 
    Any class that implements this should implement `get_difficulty(chain) -> int` method.
    """

    def get_difficulty(self, chain: "Blockchain") -> int:
        """Return the difficulty to use for the next block."""
        ... 

class FixedDifficultyPolicy:
    """Difficulty is fixed for the chain, set as a paramater and doesnt change"""

    def __init__(self, difficulty: int = DIFFICULTY) -> None:
        self.difficulty = difficulty

    def get_difficulty(self, chain: "Blockchain") -> int:
        return self.difficulty


class DynamicDifficultyPolicy:
    """Difficulty is dynamic, and updated after x amount of blocks, so that mining takes t amount of time on average (like blockchain)"""

    def get_difficulty(self, chain: "Blockchain") -> int:
        #TODO
        ...