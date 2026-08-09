CURRENT_DIR = $(shell pwd)
RUN_ID = $(shell date +%Y%m%d_%H%M%S)
PROJECT_NAME = art_scraper
include .env
export

prepare-dirs:
	mkdir -p data || true && \
	mkdir -p data/artists_raw_html || true && \
	mkdir -p data/artworks_raw_html || true && \
	mkdir -p data/art_links || true && \
	mkdir -p data/nltk_dir || true

build-network:
	docker network create service_network -d bridge || true

build:
	docker build -t ${PROJECT_NAME}:dev .

code-version:
	git log --oneline --format=%h -n1 > ${CURRENT_DIR}/src/code_vesrion.txt

run-dev:
	CONFIG_PATH=${CURRENT_DIR}/src/config.yml \
	PYTHONPATH=${CURRENT_DIR}/src \
	ROOT_DATA_DIR=${CURRENT_DIR}/data \
	python ${CURRENT_DIR}/src/main.py --pipeline wikidata

run-api:
	CONFIG_PATH=${CURRENT_DIR}/src/config.yml \
	PYTHONPATH=${CURRENT_DIR}/src \
	ROOT_DATA_DIR=${CURRENT_DIR}/data \
	APP_LABEL=${PROJECT_NAME}_api \
	uvicorn content_api:app --host 0.0.0.0 --port 8090

stop-api:
	@pkill -f "APP_LABEL=${PROJECT_NAME}_api" && echo "API stopped" || echo "API not running"

attach:
	tail -f /tmp/${PROJECT_NAME}_api.log

run: stop-api
	CONFIG_PATH=${CURRENT_DIR}/src/config.yml \
	PYTHONPATH=${CURRENT_DIR}/src \
	ROOT_DATA_DIR=${CURRENT_DIR}/data \
	APP_LABEL=${PROJECT_NAME}_api \
	nohup uvicorn content_api:app --host 0.0.0.0 --port 8090 > /tmp/${PROJECT_NAME}_api.log 2>&1 &
	@echo "API started (log: /tmp/${PROJECT_NAME}_api.log)"
	CONFIG_PATH=${CURRENT_DIR}/src/config.yml \
	PYTHONPATH=${CURRENT_DIR}/src \
	ROOT_DATA_DIR=${CURRENT_DIR}/data \
	streamlit run ${CURRENT_DIR}/src/streamlit_app.py --server.port 8501

run-app:
	CONFIG_PATH=${CURRENT_DIR}/src/config.yml \
	PYTHONPATH=${CURRENT_DIR}/src \
	ROOT_DATA_DIR=${CURRENT_DIR}/data \
	streamlit run ${CURRENT_DIR}/src/streamlit_app.py --server.port 8501


run-debug:

build-search-index: build-network code-version prepare-dirs
	docker run -it --rm \
	    --env-file ${CURRENT_DIR}/.env \
	    -v "${CURRENT_DIR}/src:/srv/src" \
	    -v "${CURRENT_DIR}/data:/srv/data" \
		--network service_network \
	    ${PROJECT_NAME}:dev "python3" src/prepare_search_index.py

run-jupyter:
	ROOT_DATA_DIR=${CURRENT_DIR}/data \
	PYTHONPATH=${CURRENT_DIR}/src \
	CONFIG_PATH=${CURRENT_DIR}/src/config.yml \
	ENV_PATH=${CURRENT_DIR}/.env \
	RUN_ENV=LOCAL \
	jupyter notebook src/jupyter_notebooks --ip 0.0.0.0 --port 8899 --NotebookApp.token='' --NotebookApp.password='' --allow-root --no-browser 


# mongo: build-network
# 	docker run -d \
# 		-v "${CURRENT_DIR}/data/mongo_data:/data/db"\
# 		-p 27018:27017 \
# 	    --name ${PROJECT_NAME}_mongo \
# 		--network service_network \
# 		mongo:6.0.5

stop-mongo:
	docker rm -f ${PROJECT_NAME}_mongo

run-inference:
	JOB_CONFIG_PATH=${CURRENT_DIR}/nebius_cloud_tuning/configs/config.yaml \
	python3 ${CURRENT_DIR}/nebius_cloud_tuning/inference.py

prepare-images:
	CONFIG_PATH=${CURRENT_DIR}/src/config.yml \
	PYTHONPATH=${CURRENT_DIR}/src \
	ROOT_DATA_DIR=${CURRENT_DIR}/data \
	python3 ${CURRENT_DIR}/src/prepare_images.py

deploy: upload-job-files
	nebius ai job create \
	    --name "art-genre-classification-prod" \
	    --image nvidia/cuda:13.1.1-runtime-ubuntu24.04 \
	    --platform gpu-l40s-a \
	    --preset 1gpu-8vcpu-32gb \
	    --disk-size 100Gi \
	    --shm-size 16Gi \
	    --volume "${BUCKET_ID}:/workspace/data" \
	    --container-command bash \
	    --args '-c "export JOB_CONFIG_PATH=/workspace/data/configs/config_prod.yaml && \
	      export OUTPUT_DIR=/workspace/data/output/${RUN_ID} && \
	      export HF_HUB_ENABLE_HF_TRANSFER=1 && \
	      apt-get update -y && \
	      apt-get install -y python3 python3-pip python3-dev && \
	      cd /workspace/data && \
	      mkdir -p output/${RUN_ID} && \
	      python3 -m pip install --no-cache-dir --break-system-packages \
	        --index-url https://download.pytorch.org/whl/cu121 \
	        torch torchvision && \
	      python3 -m pip install --no-cache-dir --break-system-packages -r requirements.txt && \
	      python3 train.py"'

upload-job-files:
	aws s3 sync \
	    ${CURRENT_DIR}/nebius_cloud_tuning \
	    s3://${S3_BUCKET} \
	    --endpoint-url ${S3_ENDPOINT} \
	    --exclude "output/*" \
	    --exclude "*.md"

predict:
	JOB_CONFIG_PATH=${CURRENT_DIR}/nebius_cloud_tuning/configs/config_local.yaml \
	python3 ${CURRENT_DIR}/nebius_cloud_tuning/inference.py

download_model:
	$(eval LATEST_RUN := $(shell aws s3 ls s3://${S3_BUCKET}/output/ \
	    --endpoint-url ${S3_ENDPOINT} \
	    | grep PRE \
	    | awk '{print $$2}' \
	    | sort \
	    | tail -1 \
	    | tr -d '/'))
	@echo "Latest run: $(LATEST_RUN)"
	aws s3 sync \
	    s3://${S3_BUCKET}/output/$(LATEST_RUN) \
	    ${CURRENT_DIR}/nebius_cloud_tuning/output/$(LATEST_RUN) \
	    --endpoint-url ${S3_ENDPOINT} \
	    --no-progress

delete-earliest-run:
	$(eval EARLIEST_RUN := $(shell aws s3 ls s3://${S3_BUCKET}/output/ \
	    --endpoint-url ${S3_ENDPOINT} \
	    | grep PRE \
	    | awk '{print $$2}' \
	    | sort \
	    | head -1 \
	    | tr -d '/'))
	@echo "Earliest run: $(EARLIEST_RUN)"
	aws s3 rm \
	    s3://${S3_BUCKET}/output/$(EARLIEST_RUN) \
	    --endpoint-url ${S3_ENDPOINT} \
	    --recursive

upload-dataset-huggingface:
	ROOT_DATA_DIR=${CURRENT_DIR}/data \
	python3 ${CURRENT_DIR}/src/prepare_images.py --upload

# One-time: tune AWS CLI transfer settings for large uploads
configure-s3-transfer:
	aws configure set default.s3.max_concurrent_requests 50
	aws configure set default.s3.multipart_threshold 64MB
	aws configure set default.s3.multipart_chunksize 64MB
	aws configure set default.s3.max_queue_size 1000

upload-dataset-s3: configure-s3-transfer
	aws s3 sync \
	    ${CURRENT_DIR}/data/hf_dataset \
	    s3://${S3_BUCKET}/hf_dataset \
	    --endpoint-url ${S3_ENDPOINT} \
	    --no-progress \
	    --cli-read-timeout 300 \
	    --cli-connect-timeout 30

analysis:
	CONFIG_PATH=${CURRENT_DIR}/src/config.yml PYTHONPATH=${CURRENT_DIR}/src \
	ROOT_DATA_DIR=${CURRENT_DIR}/data \
	python3 ${CURRENT_DIR}/src/main.py --pipeline analysis
