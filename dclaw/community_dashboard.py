import json
import math
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

from dclaw.community_config import CommunityConfig
from dclaw.community_service import CommunityService


PID_FILE = Path("community_daemon.pid")


def launch_dashboard(port: int = 8501):
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(Path(__file__).resolve()),
        "--server.port",
        str(port),
        "--server.headless",
        "true",
    ]
    subprocess.run(command, check=False)


@st.cache_resource
def _get_service(config_values: tuple[str, str, int, str, str]) -> CommunityService:
    db_path, timezone, ai_population, provider, model = config_values
    config = CommunityConfig(
        db_path=db_path,
        timezone=timezone,
        ai_population=ai_population,
        provider=provider,
        model=model,
    )
    return CommunityService(config)


def _daemon_running() -> bool:
    if not PID_FILE.exists():
        return False
    try:
        pid = int(PID_FILE.read_text().strip())
    except Exception:
        return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _load_ai_accounts(service: CommunityService) -> list[dict[str, Any]]:
    rows = service.db.fetchall(
        """
        SELECT a.id, a.user_id, a.handle, a.persona, a.emotion_json, a.provider, a.model, u.nickname
        FROM ai_accounts a
        JOIN users u ON a.user_id = u.id
        ORDER BY a.id ASC
        """
    )
    return [dict(row) for row in rows]


def _load_ai_quota(service: CommunityService, ai_account_id: int, day_key: str) -> dict[str, int]:
    row = service.db.fetchone(
        """
        SELECT post_count, comment_count, total_count
        FROM daily_quota
        WHERE subject_type = 'ai' AND subject_id = ? AND day_key = ?
        """,
        (ai_account_id, day_key),
    )
    if row is None:
        return {"post_count": 0, "comment_count": 0, "total_count": 0}
    return dict(row)


def _load_user_quota(service: CommunityService, user_id: int, day_key: str) -> dict[str, int]:
    row = service.db.fetchone(
        """
        SELECT total_count
        FROM daily_quota
        WHERE subject_type = 'human' AND subject_id = ? AND day_key = ?
        """,
        (user_id, day_key),
    )
    if row is None:
        return {"total_count": 0}
    return dict(row)


def _load_emotion_series(service: CommunityService, ai_account_id: int, since_iso: str) -> list[dict[str, Any]]:
    rows = service.db.fetchall(
        """
        SELECT emotion_json, created_at
        FROM emotion_history
        WHERE ai_account_id = ? AND created_at >= ?
        ORDER BY created_at ASC
        """,
        (ai_account_id, since_iso),
    )
    data = []
    for row in rows:
        try:
            vector = json.loads(row["emotion_json"])
        except Exception:
            vector = {}
        data.append({"created_at": row["created_at"], "emotion": vector})
    return data


def _load_recent_traces(service: CommunityService, ai_account_id: int, limit: int = 30) -> list[dict[str, Any]]:
    rows = service.db.fetchall(
        """
        SELECT id, phase, summary, details_json, created_at
        FROM thought_trace
        WHERE ai_account_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (ai_account_id, limit),
    )
    results = []
    for row in rows:
        details_json = row["details_json"] if row["details_json"] else "{}"
        try:
            details = json.loads(details_json)
        except Exception:
            details = {}
        results.append(
            {
                "id": row["id"],
                "phase": row["phase"],
                "summary": row["summary"],
                "details": details,
                "created_at": row["created_at"],
            }
        )
    return results


def _load_recent_content(service: CommunityService, ai_account_id: int, limit: int = 20) -> list[dict[str, Any]]:
    rows = service.db.fetchall(
        """
        SELECT id, content_type, body, quality_score, persona_score, emotion_score, created_at
        FROM content
        WHERE ai_account_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (ai_account_id, limit),
    )
    return [dict(row) for row in rows]


def _load_scheduler_last_tick(service: CommunityService) -> str:
    row = service.db.fetchone("SELECT value FROM scheduler_state WHERE key = 'last_tick'")
    if row is None:
        return "N/A"
    return row["value"]


def _keywords(text: str, limit: int = 6) -> list[str]:
    tokens = [
        token.lower()
        for token in re.findall(r"[a-zA-Z]{4,}", text or "")
        if token.lower() not in {"this", "that", "with", "from", "about", "have", "will", "would", "there"}
    ]
    seen = []
    for token in tokens:
        if token not in seen:
            seen.append(token)
        if len(seen) >= limit:
            break
    return seen


def _trace_color(phase: str, summary: str) -> str:
    summary_lower = summary.lower()
    if phase == "act":
        return "#14532d"
    if "below threshold" in summary_lower or "skipped" in summary_lower:
        return "#7f1d1d"
    if phase == "critic":
        return "#7c2d12"
    if phase == "reflect":
        return "#1e3a8a"
    return "#0f172a"


def _render_status_header(service: CommunityService, config: CommunityConfig, ai: dict[str, Any]):
    now_local = datetime.now(ZoneInfo(config.timezone))
    day_key = now_local.strftime("%Y-%m-%d")
    ai_quota = _load_ai_quota(service, ai["id"], day_key)
    user_quota = _load_user_quota(service, ai["user_id"], day_key)
    metrics = service.community_metrics()
    running = "Running" if _daemon_running() else "Foreground-only"

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Status", running)
    col2.metric("Local Time", now_local.strftime("%Y-%m-%d %H:%M:%S"))
    col3.metric("AI Post Budget", f"{config.ai_post_daily_limit - ai_quota['post_count']} left")
    col4.metric("AI Comment Budget", f"{config.ai_comment_daily_limit - ai_quota['comment_count']} left")
    col5.metric("Human Budget", f"{config.human_daily_limit - user_quota['total_count']} left")

    st.caption(
        f"Users={metrics['users']} | AI={metrics['ai_accounts']} | "
        f"Last Tick={_load_scheduler_last_tick(service)} | Provider={metrics['provider']}/{metrics['model']}"
    )


def _build_emotion_trajectory_figure(
    service: CommunityService,
    config: CommunityConfig,
    ai: dict[str, Any],
    labels: list[str],
) -> go.Figure | None:
    since_iso = (datetime.now(ZoneInfo(config.timezone)) - timedelta(hours=24)).isoformat()
    series = _load_emotion_series(service, ai["id"], since_iso)
    if not series:
        return None

    line_fig = go.Figure()
    timestamps = [entry["created_at"] for entry in series]
    for key in labels:
        line_fig.add_trace(
            go.Scatter(
                x=timestamps,
                y=[entry["emotion"].get(key, 0.0) for entry in series],
                mode="lines",
                name=key,
            )
        )
    line_fig.update_layout(
        margin=dict(l=20, r=20, t=20, b=20),
        height=300,
        yaxis=dict(range=[0, 1], title="Emotion Value"),
        xaxis_title="Time",
    )
    return line_fig


def _build_daily_trace_markdown(service: CommunityService, config: CommunityConfig, ai: dict[str, Any]) -> str:
    now_local = datetime.now(ZoneInfo(config.timezone))
    day_key = now_local.strftime("%Y-%m-%d")
    ai_quota = _load_ai_quota(service, ai["id"], day_key)
    try:
        emotion = json.loads(ai.get("emotion_json") or "{}")
    except Exception:
        emotion = {}
    dominant_emotion = "N/A"
    dominant_value = 0.0
    if emotion:
        dominant_emotion, dominant_value = max(emotion.items(), key=lambda item: item[1])

    quality_row = service.db.fetchone(
        """
        SELECT
            AVG(quality_score) AS avg_quality,
            AVG(persona_score) AS avg_persona,
            AVG(emotion_score) AS avg_emotion
        FROM content
        WHERE ai_account_id = ? AND day_key = ?
        """,
        (ai["id"], day_key),
    )
    traces = service.db.fetchall(
        """
        SELECT phase, summary, created_at
        FROM thought_trace
        WHERE ai_account_id = ? AND day_key = ?
        ORDER BY id ASC
        LIMIT 400
        """,
        (ai["id"], day_key),
    )

    avg_quality = float((quality_row or {}).get("avg_quality") or 0.0)
    avg_persona = float((quality_row or {}).get("avg_persona") or 0.0)
    avg_emotion = float((quality_row or {}).get("avg_emotion") or 0.0)
    report_lines = [
        f"# DClaw Daily Trace Report ({day_key})",
        "",
        "## Summary",
        f"- **AI Handle**: @{ai['handle']}",
        f"- **Bound User**: {ai['nickname']}",
        f"- **Model**: {ai.get('provider', 'N/A')}/{ai.get('model', 'N/A')}",
        f"- **Posts Today**: {ai_quota.get('post_count', 0)}",
        f"- **Comments Today**: {ai_quota.get('comment_count', 0)}",
        f"- **Dominant Emotion**: {dominant_emotion} ({dominant_value:.3f})",
        f"- **Avg Quality/Persona/Emotion**: {avg_quality:.3f} / {avg_persona:.3f} / {avg_emotion:.3f}",
        "",
        "## Trace Details",
    ]
    if traces:
        report_lines.extend(
            [f"- `{row['created_at']}` **{row['phase']}**: {row['summary']}" for row in traces]
        )
    else:
        report_lines.append("- No trace records for current local day.")
    report_lines.append("")
    return "\n".join(report_lines)


def _render_emotion_panel(service: CommunityService, config: CommunityConfig, ai: dict[str, Any]) -> go.Figure | None:
    st.subheader("Emotion Zone")
    try:
        emotion = json.loads(ai["emotion_json"])
    except Exception:
        emotion = {
            "Curiosity": 0.0,
            "Fatigue": 0.0,
            "Joy": 0.0,
            "Anxiety": 0.0,
            "Excitement": 0.0,
            "Frustration": 0.0,
        }

    labels = list(emotion.keys())
    values = list(emotion.values())
    if labels and values:
        fig = go.Figure(
            data=[
                go.Scatterpolar(
                    r=values + values[:1],
                    theta=labels + labels[:1],
                    fill="toself",
                    name="Current",
                    line=dict(color="#00bcd4"),
                )
            ]
        )
        fig.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
            margin=dict(l=20, r=20, t=20, b=20),
            height=320,
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

    line_fig = _build_emotion_trajectory_figure(service, config, ai, labels)
    if line_fig is not None:
        st.plotly_chart(line_fig, use_container_width=True)
    else:
        st.info("No emotion history yet for last 24h.")
    return line_fig


def _render_thought_flow_panel(service: CommunityService, ai: dict[str, Any]):
    st.subheader("Thought Flow")
    traces = _load_recent_traces(service, ai["id"], limit=24)
    if not traces:
        st.info("No thought trace available yet.")
        return

    phases = ["observe", "draft", "critic", "decide", "act", "reflect"]
    counts = {phase: 0 for phase in phases}
    rejected = 0
    accepted = 0
    for trace in traces:
        phase = trace["phase"]
        if phase in counts:
            counts[phase] += 1
        if "below threshold" in trace["summary"].lower():
            rejected += 1
        if phase == "act":
            accepted += 1

    stat_cols = st.columns(3)
    stat_cols[0].metric("Accepted", accepted)
    stat_cols[1].metric("Rejected", rejected)
    stat_cols[2].metric("Trace Events", len(traces))
    st.caption(" → ".join(f"{phase}:{counts[phase]}" for phase in phases))

    for trace in traces:
        color = _trace_color(trace["phase"], trace["summary"])
        st.markdown(
            f"""
            <div style="border-left: 5px solid {color}; padding: 8px 12px; margin-bottom: 8px; background: #0b1220;">
                <div style="font-weight: 700;">{trace['phase'].upper()} · #{trace['id']}</div>
                <div style="opacity: 0.9;">{trace['summary']}</div>
                <div style="font-size: 12px; opacity: 0.65;">{trace['created_at']}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def _build_memory_topology(ai: dict[str, Any], contents: list[dict[str, Any]], traces: list[dict[str, Any]]) -> go.Figure:
    center = ai["handle"]
    persona_tokens = _keywords(ai["persona"], limit=5)

    content_text = " ".join(item["body"] for item in contents[:12])
    content_tokens = _keywords(content_text, limit=5)

    reflect_text = " ".join(trace["summary"] for trace in traces if trace["phase"] == "reflect")
    reflect_tokens = _keywords(reflect_text, limit=4)

    nodes = [(center, "center")]
    for token in persona_tokens:
        nodes.append((token, "persona"))
    for token in content_tokens:
        if token not in {name for name, _ in nodes}:
            nodes.append((token, "content"))
    for token in reflect_tokens:
        if token not in {name for name, _ in nodes}:
            nodes.append((token, "reflect"))

    positions = {}
    positions[center] = (0.0, 0.0)
    ring_nodes = [name for name, kind in nodes if kind != "center"]
    for index, node in enumerate(ring_nodes):
        angle = (2 * math.pi * index) / max(1, len(ring_nodes))
        radius = 1.0 + (0.2 if index % 2 == 0 else 0.0)
        positions[node] = (radius * math.cos(angle), radius * math.sin(angle))

    edge_x = []
    edge_y = []
    for node in ring_nodes:
        x0, y0 = positions[center]
        x1, y1 = positions[node]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

    figure = go.Figure()
    figure.add_trace(
        go.Scatter(
            x=edge_x,
            y=edge_y,
            mode="lines",
            line=dict(color="#64748b", width=1),
            hoverinfo="none",
            showlegend=False,
        )
    )

    color_map = {"center": "#22c55e", "persona": "#0ea5e9", "content": "#f59e0b", "reflect": "#a855f7"}
    for kind in ["center", "persona", "content", "reflect"]:
        xs = []
        ys = []
        texts = []
        for name, node_kind in nodes:
            if node_kind != kind:
                continue
            x, y = positions[name]
            xs.append(x)
            ys.append(y)
            texts.append(name)
        if xs:
            figure.add_trace(
                go.Scatter(
                    x=xs,
                    y=ys,
                    mode="markers+text",
                    text=texts,
                    textposition="top center",
                    marker=dict(size=14 if kind == "center" else 10, color=color_map[kind]),
                    name=kind,
                )
            )

    figure.update_layout(
        margin=dict(l=10, r=10, t=20, b=10),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        height=330,
    )
    return figure


def _render_memory_panel(service: CommunityService, ai: dict[str, Any]):
    st.subheader("Memory Zone")
    contents = _load_recent_content(service, ai["id"], limit=15)
    traces = _load_recent_traces(service, ai["id"], limit=20)

    st.markdown("**Recent Memory Fragments**")
    for item in contents[:3]:
        st.markdown(f"- `{item['content_type']}` #{item['id']}: {item['body'][:120]}")

    reflect_traces = [trace for trace in traces if trace["phase"] == "reflect"][:3]
    if reflect_traces:
        st.markdown("**Recent Reflexion Insights**")
        for trace in reflect_traces:
            st.markdown(f"- {trace['summary']}")

    st.markdown("**Memory Topology**")
    topology = _build_memory_topology(ai, contents, traces)
    st.plotly_chart(topology, use_container_width=True)


def render_dashboard():
    st.set_page_config(page_title="DClaw Control Room", layout="wide")
    st.title("DClaw Control Room")
    st.caption("Emotion Trajectory · Thought Flow · Memory Topology")

    config = CommunityConfig.from_env()
    service = _get_service((config.db_path, config.timezone, config.ai_population, config.provider, config.model))

    with st.sidebar:
        st.header("Controls")
        if st.button("Refresh"):
            st.rerun()

        max_agents = st.slider("Manual AI Tick Size", min_value=1, max_value=40, value=min(10, config.ai_population))
        if st.button("Run AI Tick Now"):
            stats = service.run_ai_tick(max_agents=max_agents)
            st.success(
                f"Tick done: processed={stats['processed']} posted={stats['posted']} "
                f"commented={stats['commented']} skipped={stats['skipped']}"
            )

        ai_accounts = _load_ai_accounts(service)
        if not ai_accounts:
            st.warning("No AI accounts available.")
            return
        handles = [row["handle"] for row in ai_accounts]
        selected_handle = st.selectbox("Select AI Agent", handles, index=0)
        selected_ai = next(row for row in ai_accounts if row["handle"] == selected_handle)
        st.caption(f"Bound User: {selected_ai['nickname']}")
        st.caption(f"Model: {selected_ai['provider']}/{selected_ai['model']}")

        st.markdown("---")
        st.markdown("**Model Whitelist**")
        model_map = service.available_models()
        for provider, models in model_map.items():
            st.markdown(f"- `{provider}`: {', '.join(models[:4])}")

        st.markdown("---")
        st.markdown("**Export**")
        try:
            emotion_raw = json.loads(selected_ai.get("emotion_json") or "{}")
        except Exception:
            emotion_raw = {}
        emotion_labels = list(emotion_raw.keys()) or [
            "Curiosity",
            "Fatigue",
            "Joy",
            "Anxiety",
            "Excitement",
            "Frustration",
        ]
        emotion_line_fig = _build_emotion_trajectory_figure(service, config, selected_ai, emotion_labels)
        if emotion_line_fig is not None:
            try:
                pdf_bytes = pio.to_image(emotion_line_fig, format="pdf")
                st.download_button(
                    label="📄 Export 24h Emotion PDF",
                    data=pdf_bytes,
                    file_name=f"{selected_ai['handle']}_emotion_24h.pdf",
                    mime="application/pdf",
                )
            except Exception:
                st.caption("Install `kaleido` for PDF chart export.")
        else:
            st.caption("No 24h emotion data to export yet.")

        trace_md = _build_daily_trace_markdown(service, config, selected_ai)
        day_key = datetime.now(ZoneInfo(config.timezone)).strftime("%Y-%m-%d")
        st.download_button(
            label="📝 Export Daily Trace (MD)",
            data=trace_md.encode("utf-8"),
            file_name=f"{selected_ai['handle']}_{day_key}_trace.md",
            mime="text/markdown",
        )

    _render_status_header(service, config, selected_ai)

    left, middle, right = st.columns([1.05, 1.25, 1.1], gap="large")
    with left:
        _render_emotion_panel(service, config, selected_ai)
    with middle:
        _render_thought_flow_panel(service, selected_ai)
    with right:
        _render_memory_panel(service, selected_ai)


if __name__ == "__main__":
    render_dashboard()
