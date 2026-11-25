"""Independent anemia-image research utilities; no diagnostic model is provided."""

from .quality import QA_Verdict, build_composite_qa

__all__ = ["build_composite_qa", "QA_Verdict"]
