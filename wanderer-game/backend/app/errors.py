# 本文件由 codex 辅助生成（外围模块）
class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int, details=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
