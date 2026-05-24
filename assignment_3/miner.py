from assignment_3.chain import Blockchain
from assignment_3.difficulty import DifficultyPolicy
from assignment_3.mempool import Mempool


class Miner:
    """Mining class that is stateless with respect to the chain.
    It is thread safe, so we can run it as co-routine"""

    def __init__(self, chain: Blockchain, mempool: Mempool, difficulty_policy: DifficultyPolicy):
        pass