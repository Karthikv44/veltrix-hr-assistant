"""Streamlit Web UI for Veltrix PeopleOps Assistant.

Features:
- Professional corporate interface with sidebar session & employee configuration.
- Supports Employee ID input transmitted as `Authorization: Bearer <ID>` (and `X-Employee-Id`).
- Real-time API status check against GET /health.
- Full interactive chat rendering formatted answers, policy citations, and leave confirmation proposals.
"""

import uuid

import httpx
import streamlit as st

# Set Streamlit Page Configuration
st.set_page_config(
    page_title="Veltrix PeopleOps Assistant",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for polished, professional UI styling
st.markdown(
    """
    <style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        color: #1E293B;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #64748B;
        margin-bottom: 1.5rem;
    }
    .badge-rag {
        background-color: #E0F2FE;
        color: #0369A1;
        font-weight: 600;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 0.8rem;
    }
    .badge-tool {
        background-color: #DCFCE7;
        color: #15803D;
        font-weight: 600;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 0.8rem;
    }
    .badge-refuse {
        background-color: #FEE2E2;
        color: #B91C1C;
        font-weight: 600;
        padding: 3px 8px;
        border-radius: 4px;
        font-size: 0.8rem;
    }
    .citation-box {
        background-color: #F8FAFC;
        border-left: 3px solid #3B82F6;
        padding: 8px 12px;
        margin-top: 8px;
        border-radius: 0 4px 4px 0;
        font-size: 0.85rem;
    }
    .status-ok {
        color: #10B981;
        font-weight: 600;
    }
    .status-down {
        color: #EF4444;
        font-weight: 600;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# Sidebar Configuration
with st.sidebar:
    st.image(
        "https://raw.githubusercontent.com/google/material-design-icons/master/png/action/account_balance/materialicons/48dp/2x/baseline_account_balance_black_48dp.png",
        width=48,
    )
    st.title("Veltrix PeopleOps")
    st.caption("AI-Powered HR & Leave Operations Assistant")

    st.markdown("---")
    st.subheader("Authentication & Profile")

    # Option to enter the employee ID
    auth_input = st.text_input(
        "Employee ID / Bearer Token",
        value=st.session_state.get("auth_input", "E1001"),
        help="Enter employee ID or token (e.g. 'E1001' or 'Bearer E1001').",
    )
    # Parse employee id whether user enters raw ID or Bearer format
    employee_id = auth_input.strip()
    if employee_id.lower().startswith("bearer "):
        employee_id = employee_id[7:].strip()
    st.session_state["auth_input"] = auth_input
    st.session_state["employee_id"] = employee_id

    # Session Management
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = str(uuid.uuid4())

    col_s1, col_s2 = st.columns([3, 1])
    with col_s1:
        st.text_input("Active Session ID", value=st.session_state["session_id"], disabled=True)
    with col_s2:
        if st.button("New", help="Start a new chat session"):
            st.session_state["session_id"] = str(uuid.uuid4())
            st.session_state["messages"] = []
            st.rerun()

    # API Base URL
    api_base_url = st.text_input("API Base URL", value="http://localhost:8000")

    # Backend Service Healthcheck
    st.markdown("---")
    st.subheader("System Status")
    try:
        health_resp = httpx.get(f"{api_base_url}/health", timeout=2.0)
        if health_resp.status_code == 200:
            st.markdown(
                '<span class="status-ok">● Service Operational (200 OK)</span>',
                unsafe_allow_html=True,
            )
        elif health_resp.status_code == 503:
            st.markdown(
                '<span class="status-down">● Ingesting Documents (503 Readying)</span>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<span class="status-down">● Status {health_resp.status_code}</span>',
                unsafe_allow_html=True,
            )
    except Exception:
        st.markdown(
            '<span class="status-down">● Offline (Cannot reach API)</span>', unsafe_allow_html=True
        )

    st.markdown("---")
    st.caption("Authentication Method: `X-Employee-Id: <ID>` (per spec)")
    if st.button("Clear Chat History"):
        st.session_state["messages"] = []
        st.rerun()

# Main Header
st.markdown('<div class="main-header">PeopleOps Assistant</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-header">Ask policy questions, check balances, or apply for leave with deterministic verification.</div>',
    unsafe_allow_html=True,
)

# Initialize Chat Messages
if "messages" not in st.session_state:
    st.session_state["messages"] = [
        {
            "role": "assistant",
            "content": f"Hello! I am your Veltrix PeopleOps Assistant. You are currently logged in as `{employee_id}`. How can I help you today with policies or leave?",
            "route": "greeting",
            "citations": [],
            "awaiting_confirmation": False,
        }
    ]

# Render Message History
for msg in st.session_state["messages"]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

        # Display route badges and metadata if present
        route = msg.get("route")
        if route and route != "greeting":
            badge_class = (
                "badge-rag"
                if route == "rag"
                else "badge-tool"
                if route == "tool"
                else "badge-refuse"
            )
            st.markdown(
                f'<span class="{badge_class}">Route: {route.upper()}</span>', unsafe_allow_html=True
            )

        # Display Citations if present
        citations = msg.get("citations", [])
        if citations:
            with st.expander(f"📚 Policy Citations ({len(citations)})"):
                for cit in citations:
                    doc_id = cit.get("doc_id", "Unknown")
                    title = cit.get("title", "")
                    locator = cit.get("locator", "")
                    st.markdown(
                        f"""
                        <div class="citation-box">
                            <strong>{doc_id}</strong>: {title} <br/>
                            <small><em>Reference: {locator}</em></small>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

        # Highlight action proposals if awaiting confirmation
        if msg.get("awaiting_confirmation"):
            st.info(
                "⚠️ This request requires your confirmation before it can be executed. Reply 'Yes' or 'Confirm' to proceed."
            )

# Chat Input Box
user_prompt = st.chat_input("Ask a question about HR policies or submit a leave request...")

if user_prompt:
    # Append and render user message
    st.session_state["messages"].append({"role": "user", "content": user_prompt})
    with st.chat_message("user"):
        st.markdown(user_prompt)

    # Invoke FastAPI endpoint with Bearer token authentication
    headers = {
        "Authorization": f"Bearer {employee_id.strip()}",
        "X-Employee-Id": employee_id.strip(),
        "Content-Type": "application/json",
    }
    payload = {
        "session_id": st.session_state["session_id"],
        "message": user_prompt,
    }

    with st.chat_message("assistant"), st.spinner("Analyzing request and documents..."):
        try:
            response = httpx.post(
                f"{api_base_url}/chat",
                json=payload,
                headers=headers,
                timeout=35.0,
            )

            if response.status_code == 200:
                data = response.json()
                bot_text = data.get("content", "")
                bot_route = data.get("route", "")
                bot_citations = data.get("citations", [])
                bot_confirm = data.get("awaiting_confirmation", False)

                st.markdown(bot_text)

                # Badge
                if bot_route:
                    badge_class = (
                        "badge-rag"
                        if bot_route == "rag"
                        else "badge-tool"
                        if bot_route == "tool"
                        else "badge-refuse"
                    )
                    st.markdown(
                        f'<span class="{badge_class}">Route: {bot_route.upper()}</span>',
                        unsafe_allow_html=True,
                    )

                # Citations
                if bot_citations:
                    with st.expander(f"📚 Policy Citations ({len(bot_citations)})"):
                        for cit in bot_citations:
                            doc_id = cit.get("doc_id", "Unknown")
                            title = cit.get("title", "")
                            locator = cit.get("locator", "")
                            st.markdown(
                                f"""
                                <div class="citation-box">
                                    <strong>{doc_id}</strong>: {title} <br/>
                                    <small><em>Reference: {locator}</em></small>
                                </div>
                                """,
                                unsafe_allow_html=True,
                            )

                if bot_confirm:
                    st.info(
                        "⚠️ This request requires your confirmation. Reply 'Yes' or 'Confirm' to finalize."
                    )

                # Save to state
                st.session_state["messages"].append(
                    {
                        "role": "assistant",
                        "content": bot_text,
                        "route": bot_route,
                        "citations": bot_citations,
                        "awaiting_confirmation": bot_confirm,
                    }
                )
            elif response.status_code == 401:
                err_msg = f"🔒 Authentication Failed (401): {response.text}"
                st.error(err_msg)
                st.session_state["messages"].append(
                    {"role": "assistant", "content": err_msg, "route": "refuse"}
                )
            elif response.status_code == 403:
                err_msg = f"🚫 Access Forbidden (403): {response.text}"
                st.warning(err_msg)
                st.session_state["messages"].append(
                    {"role": "assistant", "content": err_msg, "route": "refuse"}
                )
            else:
                err_msg = f"❌ Server returned error {response.status_code}: {response.text}"
                st.error(err_msg)
                st.session_state["messages"].append(
                    {"role": "assistant", "content": err_msg, "route": "error"}
                )
        except Exception as e:
            err_msg = f"⚠️ Could not reach server at {api_base_url}: {e}"
            st.error(err_msg)
            st.session_state["messages"].append(
                {"role": "assistant", "content": err_msg, "route": "error"}
            )
