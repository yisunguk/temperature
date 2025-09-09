# storage.py
import io, time
from typing import Optional
import pandas as pd
import streamlit as st
import gspread
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from gspread_dataframe import set_with_dataframe

# ── 공통 스코프 ────────────────────────────────────────────────────────────────
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
DRIVE_SCOPES  = ["https://www.googleapis.com/auth/drive"]

def _cfg(key: str, default=None):
    """항상 최신 secrets 값을 읽는다."""
    return st.secrets.get(key, default)

def _share_public() -> bool:
    return str(_cfg("SHARE_IMAGE_PUBLIC", "false")).lower() == "true"


# ── 서비스계정 클라이언트 (캐시 ok) ─────────────────────────────────────────────
def _get_sa_creds(section: str, scopes: list):
    if section not in st.secrets:
        raise RuntimeError(f"secrets.toml에 [{section}] 섹션이 없습니다.")
    sa_info = dict(st.secrets[section])
    return service_account.Credentials.from_service_account_info(sa_info, scopes=scopes)

@st.cache_resource(show_spinner=False)
def init_gsheet_client() -> gspread.Client:
    return gspread.authorize(_get_sa_creds("gsheet_service_account", SHEETS_SCOPES))

@st.cache_resource(show_spinner=False)
def init_gdrive_service():
    return build("drive", "v3", credentials=_get_sa_creds("gdrive_service_account", DRIVE_SCOPES))


# ── Sheets I/O ────────────────────────────────────────────────────────────────
def _open_sheet():
    sheet_id = _cfg("SHEET_ID")
    if not sheet_id:
        raise RuntimeError("SHEET_ID is missing in secrets.toml")
    gc = init_gsheet_client()
    return gc.open_by_key(sheet_id)

def get_or_create_worksheet():
    sh = _open_sheet()
    ws_name = _cfg("WORKSHEET_NAME", "data")
    try:
        ws = sh.worksheet(ws_name)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=ws_name, rows=200, cols=10)
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


# ── Drive 업로드 (서비스계정, 공유드라이브용 옵션) ──────────────────────────────
def upload_image_to_drive(image_bytes: bytes, filename_prefix="photo", mime_type: str = "image/jpeg") -> str:
    folder_id = _cfg("DRIVE_FOLDER_ID")
    if not folder_id:
        raise RuntimeError("DRIVE_FOLDER_ID가 secrets.toml에 없습니다.")
    drive = init_gdrive_service()

    media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype=mime_type, resumable=False)
    filename = f"{filename_prefix}_{int(time.time())}{'.png' if mime_type=='image/png' else '.jpg'}"
    file = drive.files().create(
        body={"name": filename, "parents": [folder_id]},
        media_body=media,
        fields="id, webViewLink, webContentLink",
        # supportsAllDrives=True,  # 공유 드라이브를 쓴다면 주석 해제
    ).execute()

    file_id = file["id"]
    if _share_public():
        try:
            drive.permissions().create(fileId=file_id, body={"role": "reader", "type": "anyone"}).execute()
            file = drive.files().get(fileId=file_id, fields="webViewLink, webContentLink").execute()
        except Exception:
            pass
    return file.get("webViewLink") or file.get("webContentLink") or f"https://drive.google.com/file/d/{file_id}/view"


# ── Drive 업로드 (사용자 OAuth → My Drive) ─────────────────────────────────────
def upload_image_to_drive_user(creds, image_bytes: bytes, filename_prefix="photo", mime_type: str = "image/jpeg") -> str:
    drive = build("drive", "v3", credentials=creds)
    media = MediaIoBaseUpload(io.BytesIO(image_bytes), mimetype=mime_type, resumable=False)
    filename = f"{filename_prefix}_{int(time.time())}{'.png' if mime_type=='image/png' else '.jpg'}"
    body = {"name": filename}
    folder_id = _cfg("DRIVE_FOLDER_ID")  # 있으면 해당 폴더(로그인 사용자 접근 가능해야 함)
    if folder_id:
        body["parents"] = [folder_id]
    file = drive.files().create(body=body, media_body=media, fields="id, webViewLink, webContentLink").execute()

    file_id = file["id"]
    if _share_public():
        try:
            drive.permissions().create(fileId=file_id, body={"role": "reader", "type": "anyone"}).execute()
            file = drive.files().get(fileId=file_id, fields="webViewLink, webContentLink").execute()
        except Exception:
            pass
    return file.get("webViewLink") or file.get("webContentLink") or f"https://drive.google.com/file/d/{file_id}/view"


# ── 진단 ───────────────────────────────────────────────────────────────────────
def diagnose_permissions():
    info = {
        "sheet_id": _cfg("SHEET_ID"),
        "worksheet_name": _cfg("WORKSHEET_NAME", "data"),
        "gsheets_sa": None,
        "open_by_key_ok": None,
        "error": None,
    }
    try:
        info["gsheets_sa"] = st.secrets["gsheet_service_account"].get("client_email")
    except Exception:
        info["gsheets_sa"] = "(missing [gsheet_service_account] in secrets)"

    # SHEET_ID 없으면 바로 원인 리턴
    if not info["sheet_id"]:
        info["open_by_key_ok"] = False
        info["error"] = "SHEET_ID is missing in secrets.toml"
        return info

    try:
        gc = init_gsheet_client()
        gc.open_by_key(info["sheet_id"])
        info["open_by_key_ok"] = True
    except Exception as e:
        info["open_by_key_ok"] = False
        info["error"] = str(e)
    return info


def diagnose_drive():
    info = {
        "drive_folder_id": _cfg("DRIVE_FOLDER_ID"),
        "gdrive_sa": None,
        "folder_ok": None,
        "can_create_in_folder": None,
        "error": None,
    }
    try:
        info["gdrive_sa"] = st.secrets["gdrive_service_account"].get("client_email")
    except Exception:
        info["gdrive_sa"] = "(missing [gdrive_service_account] in secrets)"

    folder_id = info["drive_folder_id"]
    if not folder_id:
        info["error"] = "DRIVE_FOLDER_ID is missing in secrets.toml"
        return info

    try:
        drive = init_gdrive_service()
        folder = drive.files().get(fileId=folder_id, fields="id,name,mimeType").execute()
        info["folder_ok"] = (folder.get("mimeType") == "application/vnd.google-apps.folder")
        media = MediaIoBaseUpload(io.BytesIO(b"diag"), mimetype="text/plain", resumable=False)
        tmp = drive.files().create(body={"name": "_diag.txt", "parents": [folder_id]},
                                   media_body=media, fields="id").execute()
        drive.files().delete(fileId=tmp["id"]).execute()
        info["can_create_in_folder"] = True
    except Exception as e:
        info["error"] = str(e)
        info["can_create_in_folder"] = False
    return info
