import streamlit as st
from agents import graph_out, config

# Streamlit page setup
st.set_page_config(page_title="Multi-Agent Legal Adviser")
st.title("🧑‍⚖️ Legal Adviser (GDPR & AI Act)")

# Session state for chat history
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []


# Display chat history
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Chat Input Handling
if user_input := st.chat_input("Ask me about your company's compliance concerns"):
    st.session_state.chat_history.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)

    with st.chat_message("assistant"):
        response_container = st.empty()
        for event in graph_out.stream({"messages": [{"role": "user", "content": user_input}]}, config, stream_mode="updates"):
            #for value in event.values():
            #print(event.keys())
            if '__interrupt__' not in event:
                for value in event.values():
                    msg=value['messages'][-1].content
                    role=list(event.keys())[0]
                    st.session_state.chat_history.append({"role": role, "content": msg})
                    response_container.markdown(msg)
