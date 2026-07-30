import os,pytest
@pytest.mark.vlm_integration
@pytest.mark.skipif(not os.getenv("RUN_VLM_INTEGRATION"),reason="requires local Ollama model")
def test_real_model_enabled_explicitly(): assert os.getenv("OLLAMA_BASE_URL")
