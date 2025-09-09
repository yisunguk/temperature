# storage.py
import io
import time
from typing import Tuple, Optional
import streamlit as st
import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from gspread_dataframe import set_with_dataframe
import pandas as pd

# ===== App secrets =====
SHEET_ID = st.secrets.get("SHEET_ID")
DRIVE_FOLDER_ID = st.secrets.get("DRIVE_FOLDER_ID")
WORKSHEET_NAME = st.secrets.get("WORKSHEET_NAME", "data")
SHARE_IMAGE_PUBLIC = str(st.secrets.get("SHARE_IMAGE_PUBLIC", "false")).lower() == "true"

# ===== Scopes =====
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]


def _get_creds_from_section(section: str, scopes: list):
    """secrets.toml 의 [section] 블록(dict)을 Credentials로 변환"""
    if section not in st.secrets:
        raise RuntimeError(f"secrets.toml에 [{section}] 섹션이 없습니다.")
    sa_info = dict(st.secrets[section])
    return service_account.Credentials.from_service_account_info(sa_info, scopes=scopes)


@st.cache_resource(show_spinner=False)
def init_gsheet_client() -> gspread.Client:
    """gsheet_service_account 로 gspread 클라이언트 생성"""
    creds = _get_creds_from_section("gsheet_service_account", SHEETS_SCOPES)
    return gspread.authorize(creds)


@st.cache_resource(show_spinner=False)
def init_gdrive_service():
    """gdrive_service_account 로 Drive v3 서비스 생성"""
    creds = _get_creds_from_section("gdrive_service_account", DRIVE_SCOPES)
    return build("drive", "v3", credentials=creds)


def get_or_create_worksheet():
    if not SHEET_ID:
        raise RuntimeError("SHEET_ID가 secrets.toml에 설정되어 있지 않습니다.")
    gc = init_gsheet_client()
    sh = gc.open_by_key(SHEET_ID)
    try:
        ws = sh.worksheet(WORKSHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=WORKSHEET_NAME, rows=100, cols=10)
        # 헤더 생성
        ws.update("A1:D1", [["일자", "온도(℃)", "습도(%)", "사진URL"]])
    return ws


def read_dataframe() -> pd.DataFrame:
    ws = get_or_create_worksheet()
    data = ws.get_all_records()
    df = pd.DataFrame(data)
    if df.empty:
        df = pd.DataFrame(columns=["일자", "온도(℃)", "습도(%)", "사진URL"])
    return df


def append_row(date_str: str, temp: Optional[float], humid: Optional[float], image_url: str):
    ws = get_or_create_worksheet()
    ws.append_row([date_str, temp, humid, image_url], value_input_option="USER_ENTERED")


def replace_all(df: pd.DataFrame):
    ws = get_or_create_worksheet()
    ws.clear()
    set_with_dataframe(ws, df)


def upload_image_to_drive(image_bytes: bytes, filename_prefix="photo", mime_type: str = "image/jpeg") -> str:
    """
    이미지를 Google Drive 폴더(DRIVE_FOLDER_ID)에 업로드하고 웹 링크를 반환합니다.
    mime_type: "image/jpeg" | "image/png" 등
    """
    if not DRIVE_FOLDER_ID:
        raise RuntimeError("DRIVE_FOLDER_ID가 secrets.toml에 없습니다.")

    drive = init_gdrive_service()
    media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype=mime_type, resumable=False)
    filename = f"{filename_prefix}_{int(time.time())}{'.png' if mime_type=='image/png' else '.jpg'}"

    try:
        file = drive.files().create(
            body={"name": filename, "parents": [DRIVE_FOLDER_ID]},
            media_body=media,
            fields="id, webViewLink, webContentLink",
        ).execute()
    except Exception as e:
        # 가능한 원인: 권한 부족, 폴더ID 오타, 서비스계정 공유 누락
        raise RuntimeError(f"Drive 업로드 실패: {e!r}")

    file_id = file["id"]

    # 공개 설정 (옵션)
    if SHARE_IMAGE_PUBLIC:
        try:
            drive.permissions().create(
                fileId=file_id,
                body={"role": "reader", "type": "anyone"},
            ).execute()
            file = drive.files().get(fileId=file_id, fields="webViewLink, webContentLink").execute()
        except Exception:
            # 권한 공개 실패해도 업로드는 성공이므로 무시
            pass

    return file.get("webViewLink") or file.get("webContentLink") or f"https://drive.google.com/file/d/{file_id}/view"


def diagnose_permissions():
    """Sheets 접근 진단"""
    info = {
        "sheet_id": SHEET_ID,
        "worksheet_name": WORKSHEET_NAME,
        "gsheets_sa": None,
        "open_by_key_ok": None,
        "error": None,
    }
    try:
        info["gsheets_sa"] = st.secrets["gsheet_service_account"].get("client_email")
    except Exception:
        info["gsheets_sa"] = "(missing [gsheet_service_account] in secrets)"

    try:
        gc = init_gsheet_client()
        gc.open_by_key(SHEET_ID)  # 권한/ID 검증
        info["open_by_key_ok"] = True
    except Exception as e:
        info["open_by_key_ok"] = False
        info["error"] = str(e)
    return info


def diagnose_drive():
    """Drive 연결/권한 진단: 폴더 조회 및 임시 파일 생성/삭제 테스트"""
    info = {"drive_folder_id": DRIVE_FOLDER_ID, "gdrive_sa": None,
            "folder_ok": None, "can_create_in_folder": None, "error": None}
    try:
        info["gdrive_sa"] = st.secrets["gdrive_service_account"].get("client_email")
    except Exception:
        info["gdrive_sa"] = "(missing [gdrive_service_account] in secrets)"

    try:
        drive = init_gdrive_service()
        folder = drive.files().get(fileId=DRIVE_FOLDER_ID, fields="id,name,mimeType").execute()
        info["folder_ok"] = (folder.get("mimeType") == "application/vnd.google-apps.folder")
        media = MediaIoBaseUpload(io.BytesIO(b"diag"), mimetype="text/plain", resumable=False)
        tmp = drive.files().create(body={"name":"_diag.txt","parents":[DRIVE_FOLDER_ID]},
                                   media_body=media, fields="id").execute()
        drive.files().delete(fileId=tmp["id"]).execute()
        info["can_create_in_folder"] = True
    except Exception as e:
        info["error"] = str(e); info["can_create_in_folder"] = False
    return info

