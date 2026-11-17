"""쇼핑 리스트 Streamlit 앱"""

import json
import os
import tempfile
import threading
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="쇼핑 리스트", page_icon="🛒", layout="centered")

# 새로고침해도 데이터가 유지되도록 아이템을 JSON 파일에 저장한다.
# 환경변수 SHOPPING_DATA_FILE로 저장 위치를 바꿀 수 있다(테스트용).
DATA_FILE = Path(os.environ.get("SHOPPING_DATA_FILE", Path(__file__).parent / "data" / "items.json"))

MAX_NAME_LEN = 100  # 아이템 이름 최대 글자 수
MAX_ITEMS = 200  # 목록에 담을 수 있는 최대 아이템 수


# ---------------------------------------------------------------- 저장/불러오기
def load_data() -> dict:
    """파일에서 {"items": [...], "next_id": int}를 읽는다.

    파일이 없거나 손상되었으면 빈 데이터를 반환한다.
    예전 형식(아이템 리스트만 있는 파일)도 읽을 수 있다.
    """
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            raw = {"items": raw}
        items = [
            {"id": int(i["id"]), "name": str(i["name"]), "checked": bool(i["checked"])}
            for i in raw["items"]
        ]
        # next_id는 한 번 쓴 ID를 다시 쓰지 않도록 파일에 같이 저장한다.
        next_id = max(int(raw.get("next_id", 1)), max((i["id"] for i in items), default=0) + 1)
        return {"items": items, "next_id": next_id}
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return {"items": [], "next_id": 1}


def save_data(data: dict) -> bool:
    """데이터를 파일에 저장한다. (임시 파일에 쓴 뒤 교체해서 손상을 막는다.) 성공 여부를 반환."""
    tmp = None
    try:
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=DATA_FILE.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)
        return True
    except OSError:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False


@st.cache_resource
def _file_lock() -> threading.Lock:
    """모든 세션이 공유하는 락. (스크립트가 재실행되어도 같은 객체를 돌려준다.)"""
    return threading.Lock()


def _mutate(fn) -> None:
    """파일의 최신 데이터를 읽어 fn으로 고친 뒤 저장한다.

    세션이 가진 오래된 목록이 아니라 항상 파일의 최신 상태를 기준으로 수정하므로,
    다른 탭/세션의 변경을 덮어쓰지 않는다. 읽기-수정-쓰기 구간은 락으로 보호한다.
    """
    with _file_lock():
        data = load_data()
        fn(data)
        ok = save_data(data)
    st.session_state["items"] = data["items"]
    st.session_state.save_failed = not ok


def sync_items() -> None:
    """화면을 그리기 전에 파일의 최신 목록을 가져온다."""
    with _file_lock():
        st.session_state["items"] = load_data()["items"]


# ---------------------------------------------------------------- 상태 관리
def init_state() -> None:
    """화면 상태용 session_state를 초기화한다. (아이템 목록은 sync_items가 채운다.)"""
    if "save_failed" not in st.session_state:
        st.session_state.save_failed = False
    if "editing_id" not in st.session_state:
        st.session_state.editing_id = None  # 수정 중인 아이템 ID (없으면 None)
    if "add_error" not in st.session_state:
        st.session_state.add_error = None  # 추가 시 보여줄 경고 문구 (없으면 None)
    if "edit_error" not in st.session_state:
        st.session_state.edit_error = False  # 수정 시 빈 입력 경고 표시 여부


def _find_item(item_id: int):
    """세션 목록에서 ID로 아이템을 찾는다. 없으면 None."""
    for item in st.session_state["items"]:
        if item["id"] == item_id:
            return item
    return None


def _clear_errors() -> None:
    st.session_state.add_error = None
    st.session_state.edit_error = False


def _end_edit() -> None:
    """수정 모드를 종료하고 수정용 입력 상태를 정리한다."""
    editing_id = st.session_state.editing_id
    if editing_id is not None:
        st.session_state.pop(f"edit_{editing_id}", None)
    st.session_state.editing_id = None


# ---------------------------------------------------------------- 콜백/기능
def add_item() -> None:
    """입력창의 이름으로 아이템을 목록 맨 아래에 추가한다. (폼 제출 콜백)"""
    name = st.session_state.get("new_item", "").strip()
    _clear_errors()
    if not name:
        st.session_state.add_error = "아이템 이름을 입력해주세요."
        return

    rejected = []

    def apply(data: dict) -> None:
        if len(data["items"]) >= MAX_ITEMS:
            rejected.append(True)
            return
        data["items"].append({"id": data["next_id"], "name": name, "checked": False})
        data["next_id"] += 1

    _mutate(apply)
    if rejected:
        st.session_state.add_error = f"아이템은 최대 {MAX_ITEMS}개까지 추가할 수 있어요."


def start_edit(item_id: int) -> None:
    """수정 모드로 전환한다. 한 번에 한 항목만 수정할 수 있다."""
    _clear_errors()
    _end_edit()
    item = _find_item(item_id)
    if item is None:
        return
    st.session_state.editing_id = item_id
    st.session_state[f"edit_{item_id}"] = item["name"]


def update_item(item_id: int) -> None:
    """수정 입력값을 저장한다. 빈 값이면 저장하지 않고 수정 모드를 유지한다."""
    # 입력창 on_change와 저장 버튼이 같은 rerun에서 둘 다 호출될 수 있으므로
    # 이미 수정이 끝난 항목이면 무시한다.
    if st.session_state.editing_id != item_id:
        return
    name = st.session_state.get(f"edit_{item_id}", "").strip()
    _clear_errors()
    if not name:
        st.session_state.edit_error = True
        return

    def apply(data: dict) -> None:
        for item in data["items"]:
            if item["id"] == item_id:  # 다른 탭에서 이미 삭제됐으면 아무것도 하지 않는다.
                item["name"] = name

    _mutate(apply)
    _end_edit()


def cancel_edit() -> None:
    """수정을 취소하고 원래 값을 유지한다."""
    _clear_errors()
    _end_edit()


def delete_item(item_id: int) -> None:
    """아이템을 삭제한다. 수정 중인 항목이면 수정 모드도 종료한다."""
    _clear_errors()
    if st.session_state.editing_id == item_id:
        _end_edit()

    def apply(data: dict) -> None:
        data["items"] = [i for i in data["items"] if i["id"] != item_id]

    _mutate(apply)
    st.session_state.pop(f"chk_{item_id}", None)


def toggle_item(item_id: int) -> None:
    """체크박스 값에 맞춰 아이템의 체크 상태를 갱신한다."""
    checked = bool(st.session_state.get(f"chk_{item_id}", False))

    def apply(data: dict) -> None:
        for item in data["items"]:
            if item["id"] == item_id:
                item["checked"] = checked

    _mutate(apply)


def clear_checked() -> None:
    """체크된 아이템을 모두 삭제한다."""
    _clear_errors()
    removed = []

    def apply(data: dict) -> None:
        removed.extend(i["id"] for i in data["items"] if i["checked"])
        data["items"] = [i for i in data["items"] if not i["checked"]]

    _mutate(apply)
    if st.session_state.editing_id in removed:
        _end_edit()
    for item_id in removed:
        st.session_state.pop(f"chk_{item_id}", None)


# ---------------------------------------------------------------- 화면
def _escape_md(text: str) -> str:
    """사용자 입력이 마크다운으로 해석되지 않도록 특수문자를 이스케이프한다."""
    for ch in "\\`*_{}[]()#+-.!~$<>|:&":
        text = text.replace(ch, "\\" + ch)
    return text


def render_add_form() -> None:
    with st.form("add_form", clear_on_submit=True):
        col_input, col_btn = st.columns([5, 1.4], vertical_alignment="center")
        col_input.text_input(
            "아이템 이름",
            key="new_item",
            placeholder="살 물건을 입력하세요",
            max_chars=MAX_NAME_LEN,
            label_visibility="collapsed",
        )
        col_btn.form_submit_button("추가", on_click=add_item, type="primary",
                                   use_container_width=True)
    if st.session_state.add_error:
        st.warning(st.session_state.add_error)


def render_progress() -> None:
    items = st.session_state["items"]
    total = len(items)
    if total == 0:
        return
    done = sum(1 for i in items if i["checked"])
    st.progress(done / total, text=f"전체 {total}개 중 {done}개 완료")
    if done == total:
        st.success("🎉 모두 담았어요! 쇼핑 완료!")


def render_item(item: dict) -> None:
    item_id = item["id"]
    if st.session_state.editing_id == item_id:
        # 폼으로 감싸면 입력값이 제출 시점에만 전송되어, 취소 클릭 시 입력창
        # on_change가 먼저 실행되어 저장되는 문제를 피할 수 있고 Enter로도 저장된다.
        with st.container(key=f"editrow_{item_id}"):
            with st.form(f"edit_form_{item_id}", border=False):
                col_name, col_save, col_cancel = st.columns([4, 2, 2], vertical_alignment="center")
                col_name.text_input(
                    "이름 수정",
                    key=f"edit_{item_id}",
                    max_chars=MAX_NAME_LEN,
                    label_visibility="collapsed",
                )
                col_save.form_submit_button("저장", on_click=update_item, args=(item_id,),
                                            type="primary", use_container_width=True)
                col_cancel.form_submit_button("취소", on_click=cancel_edit,
                                              use_container_width=True)
            if st.session_state.edit_error:
                st.warning("아이템 이름을 입력해주세요.")
        return

    label = _escape_md(item["name"])
    if item["checked"]:
        label = f"~~{label}~~"
    # 컨테이너 key가 CSS 클래스(st-key-...)가 되어 행 스타일의 훅으로 쓰인다.
    row_key = f"item_done_{item_id}" if item["checked"] else f"item_{item_id}"
    with st.container(key=row_key):
        col_chk, col_edit, col_del = st.columns([8, 1.2, 1.2], vertical_alignment="center")
        # 체크박스 값은 위젯 key로 session_state와 동기화한다.
        st.session_state[f"chk_{item_id}"] = item["checked"]
        col_chk.checkbox(label, key=f"chk_{item_id}", on_change=toggle_item, args=(item_id,))
        # 화면에는 아이콘만 보이고, 글자("수정"/"삭제")는 CSS로 숨겨 화면 읽기 프로그램용 이름으로 쓴다.
        col_edit.button("수정", key=f"edit_btn_{item_id}", icon=":material/edit:",
                        on_click=start_edit, args=(item_id,), help="수정",
                        use_container_width=True)
        col_del.button("삭제", key=f"del_{item_id}", icon=":material/delete:",
                       on_click=delete_item, args=(item_id,), help="삭제",
                       use_container_width=True)


def render_list() -> None:
    """아이템 목록을 렌더링한다. 미체크 항목이 위, 체크 항목이 아래."""
    items = st.session_state["items"]
    if not items:
        st.markdown(
            '<div class="empty-state"><div class="icon">🧺</div>'
            "<div>아직 추가된 아이템이 없어요.</div>"
            '<div class="sub">위 입력창에서 첫 아이템을 추가해보세요.</div></div>',
            unsafe_allow_html=True,
        )
        return
    with st.container(key="list"):
        # sorted는 안정 정렬이라 같은 그룹 안에서는 추가한 순서가 유지된다.
        for item in sorted(items, key=lambda i: i["checked"]):
            render_item(item)

    has_checked = any(i["checked"] for i in items)
    st.button("체크된 항목 모두 삭제", on_click=clear_checked, disabled=not has_checked)


CSS = """
<style>
:root { --accent: #2E9E5B; --card-bg: rgba(128,128,128,0.08); --card-border: rgba(128,128,128,0.25); }

/* 불필요한 기본 요소 정리 */
#MainMenu, footer, [data-testid="stFooter"] { visibility: hidden; }
.block-container { padding-top: 2.5rem; padding-bottom: 3rem; max-width: 640px; }

/* 헤더 */
.app-header { text-align: center; margin-bottom: 1.2rem; }
.app-header h1 { margin: 0; padding: 0; font-size: 2rem; }
.app-header .subtitle { opacity: 0.65; margin-top: 0.2rem; }

/* 입력 카드 */
[data-testid="stForm"] { background: var(--card-bg); border: 1px solid var(--card-border);
    border-radius: 14px; padding: 0.8rem; }

/* 진행률 */
[data-testid="stProgress"] > div > div > div > div { background-color: var(--accent); }
[data-testid="stProgress"] p { font-weight: 600; }

/* 목록: 행 사이 간격 */
.st-key-list { gap: 0.45rem !important; }

/* 목록 행 (카드) */
[class*="st-key-item_"], [class*="st-key-editrow_"] {
    background: var(--card-bg); border: 1px solid var(--card-border);
    border-radius: 12px; padding: 0.35rem 0.75rem;
}
[class*="st-key-item_done_"] { opacity: 0.55; }
[class*="st-key-editrow_"] { border: 2px solid var(--accent); background: rgba(46,158,91,0.10); }
[class*="st-key-editrow_"] [data-testid="stForm"] { background: transparent; border: none; padding: 0; }

/* 모바일에서도 체크박스/버튼이 한 줄 유지 */
[class*="st-key-item_"] [data-testid="stHorizontalBlock"],
[class*="st-key-editrow_"] [data-testid="stHorizontalBlock"],
[data-testid="stForm"] [data-testid="stHorizontalBlock"] { flex-wrap: nowrap !important; gap: 0.4rem; }
[class*="st-key-item_"] [data-testid="stColumn"],
[class*="st-key-editrow_"] [data-testid="stColumn"],
[data-testid="stForm"] [data-testid="stColumn"] { min-width: 0 !important; }

/* 수정 모드 버튼: 글자가 세로로 꺾이지 않게 */
[class*="st-key-editrow_"] button { white-space: nowrap; padding-left: 0.4rem; padding-right: 0.4rem; }
[class*="st-key-editrow_"] button p { white-space: nowrap; }

/* 아이콘 버튼: 글자는 화면에서만 숨기고(화면 읽기 프로그램은 읽음) 아이콘만 보이게 */
[class*="st-key-item_"] button { border: none; background: transparent; padding: 0.25rem 0; min-height: 2rem; }
[class*="st-key-item_"] button p { position: absolute; width: 1px; height: 1px; overflow: hidden;
    clip-path: inset(50%); white-space: nowrap; }
[class*="st-key-item_"] button:hover { background: rgba(128,128,128,0.2); }
[class*="st-key-edit_btn_"] button:hover { color: var(--accent); }
[class*="st-key-del_"] button:hover { color: #e5484d; }
[class*="st-key-item_"] [data-testid="stCheckbox"] label { overflow-wrap: anywhere; }

/* 빈 목록 */
.empty-state { text-align: center; padding: 2.5rem 1rem; opacity: 0.75; }
.empty-state .icon { font-size: 3rem; margin-bottom: 0.4rem; }
.empty-state .sub { font-size: 0.85rem; opacity: 0.7; margin-top: 0.2rem; }
</style>
"""


def inject_css() -> None:
    """앱 전체 스타일을 한 곳에서 주입한다."""
    st.markdown(CSS, unsafe_allow_html=True)


def render_header() -> None:
    st.markdown(
        '<div class="app-header"><h1>🛒 쇼핑 리스트</h1>'
        '<div class="subtitle">오늘 살 것을 적어보세요</div></div>',
        unsafe_allow_html=True,
    )


def main() -> None:
    init_state()
    sync_items()  # 다른 탭/세션의 변경도 반영되도록 매번 파일의 최신 목록을 읽는다.
    inject_css()

    render_header()
    if st.session_state.save_failed:
        st.error("데이터를 파일에 저장하지 못했어요. 새로고침하면 목록이 사라질 수 있어요.")
    render_add_form()
    render_progress()
    render_list()


if __name__ == "__main__":
    main()
