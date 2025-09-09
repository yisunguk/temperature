# oauth_google.py
import json
import streamlit as st
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request

def _get_oauth_conf():
    conf = st.secrets.get("google_oauth", {})
    if not conf:
        raise RuntimeError("secrets.toml에 [google_oauth] 섹션이 없습니다.")
    scopes = [s.strip() for s in conf.get("scopes", "").split(",") if s.strip()]
    if not scopes:
        scopes = [
            "https://www.googleapis.com/auth/drive.file",
            "https://www.googleapis.com/auth/drive.metadata.readonly",
        ]
    client_config = {
        "web": {
            "client_id": conf["client_id"],
            "project_id": "streamlit-app",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_secret": conf["client_secret"],
            "redirect_uris": [conf["redirect_uri"]],
        }
    }
    return client_config, scopes, conf["redirect_uri"]

def _save_creds_to_session(creds: Credentials):
    st.session_state["google_oauth_token_json"] = creds.to_json()

def _load_creds_from_session() -> Credentials | None:
    token_json = st.session_state.get("google_oauth_token_json")
    if not token_json:
        return None
    try:
        creds = Credentials.from_authorized_user_info(json.loads(token_json))
        # 자동 갱신
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save_creds_to_session(creds)
        return creds
    except Exception:
        return None

def ensure_user_drive_creds() -> Credentials:
    """
    로그인 안 돼 있으면 Google 로그인 버튼을 보여주고, 로그인 후 Credentials 반환.
    """
    # 이미 세션에 토큰이 있으면 그걸 사용
    creds = _load_creds_from_session()
    if creds and creds.valid:
        return creds

    client_config, scopes, redirect_uri = _get_oauth_conf()
    flow = Flow.from_client_config(client_config=client_config, scopes=scopes, redirect_uri=redirect_uri)

    # 콜백으로 돌아온 경우 처리 (code 파라미터)
    try:
        params = st.query_params if hasattr(st, "query_params") else st.experimental_get_query_params()
        code = params.get("code", None)
        if isinstance(code, list):  # experimental_get_query_params() 형태 대응
            code = code[0]
    except Exception:
        code = None

    if code:
        flow.fetch_token(code=code)
        creds = flow.credentials
        _save_creds_to_session(creds)
        # 주소창의 code/state 제거
        try:
            st.query_params.clear()  # 신버전
        except Exception:
            st.experimental_set_query_params()
        return creds

    # 최초 접근: 로그인 URL 생성
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent"
    )
    st.info("사진을 **개인 드라이브(My Drive)** 에 저장하려면 Google 로그인이 필요합니다.")
    st.link_button("🔐 Google로 로그인", auth_url, use_container_width=True)
    st.stop()
