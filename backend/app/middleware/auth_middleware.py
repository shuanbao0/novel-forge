"""
认证中间件 - 从签名 Cookie 中提取用户信息并注入到 request.state
"""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.user_manager import user_manager
from app.logger import get_logger
from app.security import verify_session_token

logger = get_logger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """认证中间件"""

    async def dispatch(self, request: Request, call_next):
        """从签名 Cookie 中提取用户 ID 并注入到 request.state"""
        # 优先验证签名会话 Cookie；不再信任客户端可伪造的明文 user_id。
        user_id = verify_session_token(request.cookies.get("session_token"))

        if user_id:
            user = await user_manager.get_user(user_id)
            if user:
                # 检查用户是否被禁用 (trust_level = -1)
                if user.trust_level == -1:
                    logger.warning(f"禁用用户尝试访问: {user_id} ({user.username})")
                    request.state.user_id = None
                    request.state.user = None
                    request.state.is_admin = False
                else:
                    request.state.user_id = user_id
                    request.state.user = user
                    request.state.is_admin = user.is_admin
            else:
                request.state.user_id = None
                request.state.user = None
                request.state.is_admin = False
        else:
            request.state.user_id = None
            request.state.user = None
            request.state.is_admin = False

        response = await call_next(request)
        return response
