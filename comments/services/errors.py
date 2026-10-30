class PipelineError(Exception):
    """사용자에게 그대로 안내할 수 있는 처리 실패 (F611)."""


class CompanyNotFound(PipelineError):
    pass


class NoCommentsFound(PipelineError):
    pass


class LLMError(PipelineError):
    pass
