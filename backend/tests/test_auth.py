"""认证流程测试 — 注册/登录/刷新/归属隔离/越权/公开分享

用独立内存库（StaticPool）覆盖 get_db 依赖，不碰开发库。
"""

import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models.user import User
from main import app

# ==================== 测试应用工厂（内存库） ====================

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def _override_get_db():
    db = TestSession()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db
client = TestClient(app)


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


class AuthFlowTests(unittest.TestCase):
    """注册 / 登录 / 刷新基础流程"""

    def test_register_login_refresh_flow(self):
        # 注册 → 返回双 token
        resp = client.post("/api/auth/register", json={"username": "alice", "password": "password123"})
        self.assertEqual(resp.status_code, 201)
        tokens = resp.json()
        self.assertEqual(tokens["username"], "alice")
        self.assertIn("accessToken", tokens)
        self.assertIn("refreshToken", tokens)

        # 重复注册 → 409
        dup = client.post("/api/auth/register", json={"username": "alice", "password": "password123"})
        self.assertEqual(dup.status_code, 409)

        # 弱密码 → 422
        weak = client.post("/api/auth/register", json={"username": "bob", "password": "short"})
        self.assertEqual(weak.status_code, 422)

        # 登录成功 / 失败
        ok = client.post("/api/auth/login", json={"username": "alice", "password": "password123"})
        self.assertEqual(ok.status_code, 200)
        bad = client.post("/api/auth/login", json={"username": "alice", "password": "wrong-password"})
        self.assertEqual(bad.status_code, 401)
        unknown = client.post("/api/auth/login", json={"username": "ghost", "password": "wrong-password"})
        self.assertEqual(unknown.status_code, 401)
        # 不给账号枚举信号：两种失败的提示一致
        self.assertEqual(bad.json()["detail"], unknown.json()["detail"])

        # refresh 换新 token，新 access 可用
        refreshed = client.post("/api/auth/refresh", json={"refreshToken": tokens["refreshToken"]})
        self.assertEqual(refreshed.status_code, 200)
        new_access = refreshed.json()["accessToken"]
        pages = client.get("/api/pages", headers=_bearer(new_access))
        self.assertEqual(pages.status_code, 200)

        # 用 access token 当 refresh 用 → 401（类型不符）
        misuse = client.post("/api/auth/refresh", json={"refreshToken": new_access})
        self.assertEqual(misuse.status_code, 401)

        # 篡改 token → 401
        tampered = client.get("/api/pages", headers=_bearer(tokens["accessToken"][:-2] + "xx"))
        self.assertEqual(tampered.status_code, 401)


class PageOwnershipTests(unittest.TestCase):
    """页面按 user_id 归属隔离：他人资源一律 404"""

    def _register(self, username: str) -> dict:
        resp = client.post("/api/auth/register", json={"username": username, "password": "password123"})
        return resp.json()

    def _create_page(self, token: str, title: str) -> dict:
        resp = client.post(
            "/api/pages",
            json={"title": title, "componentData": [], "canvasStyle": {}},
            headers=_bearer(token),
        )
        self.assertEqual(resp.status_code, 201)
        return resp.json()["page"]

    def test_unauthenticated_rejected(self):
        resp = client.get("/api/pages")
        self.assertEqual(resp.status_code, 401)
        resp = client.post("/api/pages", json={"title": "匿名"})
        self.assertEqual(resp.status_code, 401)
        resp = client.post("/api/ai/chat", json={"prompt": "hi"})
        self.assertEqual(resp.status_code, 401)

    def test_pages_scoped_by_owner(self):
        alice = self._register("owner_alice")
        bob = self._register("owner_bob")

        page = self._create_page(alice["accessToken"], "alice 的页面")

        # 列表只含自己的页面
        alice_list = client.get("/api/pages", headers=_bearer(alice["accessToken"])).json()["pages"]
        bob_list = client.get("/api/pages", headers=_bearer(bob["accessToken"])).json()["pages"]
        self.assertEqual([p["_id"] for p in alice_list], [page["_id"]])
        self.assertEqual(bob_list, [])

        # 他人读/改/删/分享/读版本 → 404（与不存在同语义）
        pid = page["_id"]
        self.assertEqual(client.get(f"/api/pages/{pid}", headers=_bearer(bob["accessToken"])).status_code, 404)
        self.assertEqual(
            client.put(f"/api/pages/{pid}", json={"title": "黑掉你"}, headers=_bearer(bob["accessToken"])).status_code,
            404,
        )
        self.assertEqual(client.delete(f"/api/pages/{pid}", headers=_bearer(bob["accessToken"])).status_code, 404)
        self.assertEqual(client.post(f"/api/pages/{pid}/share", headers=_bearer(bob["accessToken"])).status_code, 404)
        self.assertEqual(client.get(f"/api/pages/{pid}/versions", headers=_bearer(bob["accessToken"])).status_code, 404)

        # 归属者正常读写
        self.assertEqual(client.get(f"/api/pages/{pid}", headers=_bearer(alice["accessToken"])).status_code, 200)
        self.assertEqual(
            client.put(f"/api/pages/{pid}", json={"title": "改名"}, headers=_bearer(alice["accessToken"])).status_code,
            200,
        )

    def test_share_token_allows_anonymous_read_only(self):
        alice = self._register("sharer")
        page = self._create_page(alice["accessToken"], "公开页")
        pid = page["_id"]

        shared = client.post(f"/api/pages/{pid}/share", headers=_bearer(alice["accessToken"]))
        self.assertEqual(shared.status_code, 200)
        token = shared.json()["shareToken"]

        # 匿名凭 share token 只读
        public = client.get(f"/api/shared/{token}")
        self.assertEqual(public.status_code, 200)
        self.assertEqual(public.json()["page"]["_id"], pid)

        # 匿名写接口仍然全拒
        self.assertEqual(client.put(f"/api/pages/{pid}", json={"title": "匿名改"}).status_code, 401)

        # 取消分享后匿名不可见
        client.delete(f"/api/pages/{pid}/share", headers=_bearer(alice["accessToken"]))
        self.assertEqual(client.get(f"/api/shared/{token}").status_code, 404)

    def test_deleted_user_token_rejected(self):
        """用户被删后，其未过期 token 立即失效（校验时回查用户表）"""
        reg = client.post("/api/auth/register", json={"username": "vanish", "password": "password123"})
        token = reg.json()["accessToken"]
        self.assertEqual(client.get("/api/pages", headers=_bearer(token)).status_code, 200)

        db = TestSession()
        user = db.query(User).filter(User.username == "vanish").first()
        db.delete(user)
        db.commit()
        db.close()

        self.assertEqual(client.get("/api/pages", headers=_bearer(token)).status_code, 401)


if __name__ == "__main__":
    unittest.main()
