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
SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
]
DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive",
]

def _get_creds_from_section(section: str, scopes: list):
    """
    secrets.toml의 [section] 블록(dict)을 그대로 Credentials로 변환
    """
    if section not in st.secrets:
        raise RuntimeError(f"secrets.toml에 [{section}] 섹션이 없습니다.")
    sa_info = dict(st.secrets[section])
    return service_account.Credentials.from_service_account_info(sa_info, scopes=scopes)

@st.cache_resource(show_spinner=False)
def init_gsheet_client() -> gspread.Client:
    """
    gsheet_service_account 섹션으로 gspread 클라이언트 생성 (시트 쓰기/읽기)
    """
    creds = _get_creds_from_section("gsheet_service_account", SHEETS_SCOPES)
    return gspread.authorize(creds)

@st.cache_resource(show_spinner=False)
def init_gdrive_service():
    """
    gdrive_service_account 섹션으로 Drive v3 서비스 생성 (이미지 업로드/권한)
    """
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

def upload_image_to_drive(image_bytes: bytes, filename_prefix="photo") -> str:
    """
    이미지를 Google Drive 폴더(DRIVE_FOLDER_ID)에 업로드하고 웹 링크를 반환합니다.
    """
    if not DRIVE_FOLDER_ID:
        raise RuntimeError("DRIVE_FOLDER_ID가 secrets.toml에 설정되어 있지 않습니다.")

    drive = init_gdrive_service()
    media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype="image/jpeg", resumable=False)
    filename = f"{filename_prefix}_{int(time.time())}.jpg"

    file_metadata = {
        "name": filename,
        "parents": [DRIVE_FOLDER_ID],
    }

    file = drive.files().create(
        body=file_metadata,
        media_body=media,
        fields="id, webViewLink, webContentLink"
    ).execute()

    file_id = file["id"]

    # 공개 설정 (선택)
    if SHARE_IMAGE_PUBLIC:
        drive.permissions().create(
            fileId=file_id,
            body={"role": "reader", "type": "anyone"}
        ).execute()
        # 권한 적용 후 링크 다시 조회
        file = drive.files().get(fileId=file_id, fields="webViewLink, webContentLink").execute()

    # webViewLink가 시트에서 클릭하기 편함
    return file.get("webViewLink") or file.get("webContentLink") or f"https://drive.google.com/file/d/{file_id}/view"
