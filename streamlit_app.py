import os
import streamlit as st

# Load Groq API key from Streamlit secrets or environment
groq_key = st.secrets.get("GROQ_API_KEY", os.environ.get("GROQ_API_KEY", ""))

st.title("📈 FactFlow: Multi-Agent Market Sentiment & Reality Analyzer")
st.markdown("Analyze real-time news sentiment vs. financial market price action using autonomous agents.")

# User input query
user_query = st.text_input("Enter your market analysis query (e.g., 'Assess Ethereum right now'):")

if st.button("Run FactFlow Analysis"):
  if not groq_key:
    st.error("Groq API Key is missing! Please configure it in Streamlit Secrets.")
  elif not user_query:
    st.warning("Please enter a query to analyze.")
  else:
    with st.spinner("Running multi-agent analysis..."):
      # Set environment variable dynamically for your backend
      os.environ["GROQ_API_KEY"] = groq_key

      # TODO: Import and invoke your FactFlow core runner here
      # Example:
      # from factflow.main import run_factflow
      # result = run_factflow(user_query)

      st.success("Analysis complete!")
      st.info(
          "Results visualization goes here (integrate your agent execution"
          " output)."
      )