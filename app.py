import streamlit as st
import json
from rag.ingest import run_full_ingest
from rag.vector_store import collection_size
from pipeline import run_pipeline


def ensure_vector_store_ready() -> None:
    if collection_size() == 0:
        with st.spinner("Seeding crisis knowledge base for first run..."):
            run_full_ingest()

# 1. Page Configuration
st.set_page_config(
    page_title="Agentic Intelligence | Command Center",
    page_icon="🛡️",
    layout="wide"
)

ensure_vector_store_ready()

# 2. Sidebar: Scientific Grounding & Metadata
with st.sidebar:
    st.title("🛡️ AEGIS Logic")
    st.info("**Agentic Emergency Governance & Integration System**")
    st.divider()
    
    st.markdown("### 📚 Scientific Grounding")
    st.write("Source Model: **Blackman (2025)**")
    st.caption("Mapping Disparate Risk: Induced Seismicity and Social Vulnerability")
    
    st.divider()
    st.markdown("### 🤖 Agent Architecture")
    st.write("- **Orchestrator:** Multi-Basin Triage")
    st.write("- **Overseer:** Multi-Candidate Governance")
    st.write("- **Synthesis:** Inter-Agency Briefing")
    
    st.divider()
    st.caption("Developed by: Shawn Blackman (he/him)")
    st.caption("Environmental Science | Lehman College, CUNY")

# 3. Main Dashboard Header
st.title("🛡️ Agentic Intelligence")
st.markdown("### **System State: ACTIVE** | Authorized Channels: `ODNR` `OCC` `FEMA` `USGS` `|` `Logic Clusters:` `[Ohio` `Oklahoma]`")
st.divider()

# 4. Tactical Input Area (Responsive Vertical)
user_input = st.text_area(
    "📝 Incident Log / Dispatch Intake", 
    placeholder="Paste messy USGS logs, field reports, or citizen dispatch logs here...",
    height=180
)

# 5. Execution Logic
if st.button("🚀 Execute Agentic Coordination"):
    if user_input:
        with st.spinner("Analyzing Basin Logic & Auditing Safety Hooks..."):
            # Call the verified pipeline function
            result = run_pipeline(raw_input=user_input)
            
            # 6. Performance Metrics
            st.success(f"**Brief Confirmed** | Citation Alignment: {result.citation_score}")
            
            m1, m2, m3 = st.columns(3)
            with m1:
                st.metric("System Confidence", f"{result.confidence * 100:.0f}%")
            with m2:
                # Deduce basin based on content or metadata
                basin = "Ohio (Proximity)" if "ohio" in user_input.lower() else "Oklahoma (Basin)"
                st.metric("Logic Cluster", basin)
            with m3:
                st.metric("Safety Check", "PASSED" if result.citation_score >= 0.6 else "REJECTED")

            # 7. The Final Output
            st.markdown("---")
            st.markdown("### 📋 Final Agency Brief")
            st.write(result.content)
            
            # 8. Governance Transparency (The "Inner Monologue")
            with st.expander("🔍 View Overseer Audit Logs (Safety Receipts)"):
                st.json(result.audit_log)
    else:
        st.warning("Input required. Please enter an incident log to generate a brief.")

# 9. Global Footer
st.divider()
st.caption("AEGIS-Synthesis | Week 6 Technical Verification Build")