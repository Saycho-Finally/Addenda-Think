"""脚手架层：全部只通过 ModelAdapter 调模型（黑盒），自带记账。"""

from exocortex.scaffold.verifier import majority_vote, normalize_answer
from exocortex.scaffold.selfconsist import SelfConsistencyArm
from exocortex.scaffold.budget_guard import (BudgetGuard, TaskTier,
                                             recommended_config)

__all__ = ["SelfConsistencyArm", "majority_vote", "normalize_answer",
           "BudgetGuard", "TaskTier", "recommended_config"]
