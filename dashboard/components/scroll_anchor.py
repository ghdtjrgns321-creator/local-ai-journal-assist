"""Small helpers for preserving scroll position around long-running actions."""

from __future__ import annotations

import streamlit as st
import streamlit.components.v1 as components


def render_scroll_anchor(anchor_id: str) -> None:
    """Render a DOM anchor that can be targeted from a tiny component script."""
    st.markdown(f"<div id='{anchor_id}'></div>", unsafe_allow_html=True)


def scroll_to_anchor(anchor_id: str) -> None:
    """Scroll the parent Streamlit document to an anchor rendered in the main page."""
    components.html(
        f"""
        <script>
        const anchor = window.parent.document.getElementById("{anchor_id}");
        if (anchor) {{
            anchor.scrollIntoView({{behavior: "auto", block: "center"}});
        }}
        </script>
        """,
        height=0,
        width=0,
    )


def preserve_scroll_position(key: str = "global") -> None:
    """페이지 단위 스크롤 위치 영구 보존.

    Why: Streamlit `st.rerun()` 또는 위젯 상호작용으로 페이지가 다시 그려질 때
         기본 동작은 스크롤이 맨 위로 튕긴다. 버튼 클릭 직후 진행 표시/결과가
         아래쪽에 나타나는 화면에서는 매번 위로 점프하여 흐름이 끊긴다.
         스크롤 위치를 `sessionStorage`에 저장하고 페이지 로드 시 복원한다.

         (1) 페이지마다 다른 key 를 사용해 페이지 전환 시 위치가 섞이지 않는다.
         (2) 0/50/200 ms 단발 시도로는 spinner·progress 가 도중에 레이아웃을
             바꾸며 복원 시점을 놓친다. 1.5 초 동안 50 ms 간격으로 재시도하고,
             사용자가 스크롤하면 즉시 중단한다.
         (3) 브라우저의 자동 scroll restoration 은 SPA 패턴과 충돌하므로
             manual 로 강제해 브라우저가 임의로 위로 튕기지 못하도록 한다.
    """
    components.html(
        f"""
        <script>
        (function() {{
            const STORAGE_KEY = "_streamlit_scroll_pos__{key}";
            const LISTENER_FLAG = "_streamlit_scroll_listener__{key}";
            const win = window.parent;
            const doc = win.document.scrollingElement || win.document.documentElement;

            try {{ win.history.scrollRestoration = 'manual'; }} catch (e) {{}}

            // 1) 복원: 저장된 위치가 있으면 1.5 초 동안 50 ms 간격으로 재시도.
            const stored = win.sessionStorage.getItem(STORAGE_KEY);
            const targetY = stored !== null ? parseInt(stored, 10) : NaN;
            if (!isNaN(targetY) && targetY > 0) {{
                const start = Date.now();
                let aborted = false;
                const onUserScroll = () => {{
                    // Why: 폴링 복원 자체도 scroll 이벤트를 발생시키므로, 사용자가
                    //      목표 위치에서 30 px 이상 벗어났을 때만 의도적 스크롤로 간주.
                    if (Math.abs(win.scrollY - targetY) > 30 && Date.now() - start > 150) {{
                        aborted = true;
                        win.removeEventListener('scroll', onUserScroll, {{passive: true}});
                    }}
                }};
                win.addEventListener('scroll', onUserScroll, {{passive: true}});
                const tick = () => {{
                    if (aborted || Date.now() - start > 1500) {{
                        win.removeEventListener('scroll', onUserScroll, {{passive: true}});
                        return;
                    }}
                    if (Math.abs(win.scrollY - targetY) > 5) {{
                        win.scrollTo(0, targetY);
                    }}
                    setTimeout(tick, 50);
                }};
                requestAnimationFrame(tick);
            }}

            // 2) 기록: rerun마다 mount되므로 중복 listener 등록 방지.
            if (!win[LISTENER_FLAG]) {{
                win[LISTENER_FLAG] = true;
                win.addEventListener('scroll', () => {{
                    win.sessionStorage.setItem(STORAGE_KEY, String(win.scrollY || doc.scrollTop || 0));
                }}, {{passive: true}});
            }}
            // 3) 보존 보강: 위 listener 는 scroll 이벤트가 발생해야만 기록하므로,
            //    버튼 클릭 직후 새 rerun 이 시작될 때 직전 스크롤이 안 잡혀 있는
            //    경우를 막기 위해 mount 시점의 현재 scrollY 도 한 번 갱신해 둔다.
            const currentY = win.scrollY || doc.scrollTop || 0;
            if (currentY > 0) {{
                win.sessionStorage.setItem(STORAGE_KEY, String(currentY));
            }}
        }})();
        </script>
        """,
        height=0,
        width=0,
    )
