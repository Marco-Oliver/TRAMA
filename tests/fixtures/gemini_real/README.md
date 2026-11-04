# Fixtures Gemini reais (somente com autorização)

Copie aqui uma resposta Gemini de teste apenas depois de autorizar expressamente os trechos e revisar dados privados. O teste opt-in em `tests/test_gemini_real_fixture_optin.py` carrega um JSON local, reaproveita `_gemini_text`, `_extract_json` e `Application._clean_result`, sem rede.

Aceita resposta no formato `{"response": { ... }, "transcript": "trecho autorizado"}` ou os registros produzidos em `testes/resultado/respostas/`. Sem fixture, o teste é pulado. Nunca copie chaves de API, transcrições integrais ou dados pessoais sem autorização.
