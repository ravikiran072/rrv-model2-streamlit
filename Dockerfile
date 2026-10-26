FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py server.py model_engine.py model_utils.py landscape_engine.py index.html styles.css app.js map_style.js model_info.json DATA_PROVENANCE.json methods.html county_names.json counties.svg model_data.npz landscape_data.npz route_kernels.npz ./
ENV RRV_HOST=0.0.0.0 PORT=8765 RRV_DB=/data/expert_inputs.sqlite3
VOLUME /data
EXPOSE 8765
CMD ["python", "app.py", "--no-browser"]
