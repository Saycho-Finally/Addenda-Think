"""脚手架层：全部只通过 ModelAdapter 调模型（黑盒），自带记账。"""

from exocortex.scaffold.verifier import majority_vote, normalize_answer
from exocortex.scaffold.selfconsist import SelfConsistencyArm

__all__ = ["SelfConsistencyArm", "majority_vote", "normalize_answer"]
