# NLP HCC Coding Pipeline: Technical Implementation Reference

This document provides concrete technical guidance for engineering teams building NLP-based HCC extraction systems.

---

## Part 1: Model Architecture Specifications

### 1.1 Named Entity Recognition (NER) for Clinical Concepts

**Architecture: BiLSTM-CRF with Contextual Embeddings**

```
Input: Tokenized clinical text
│
├─ BERT Embedding Layer
│  └─ Output: [batch_size, seq_len, 768] (contextual tokens)
│
├─ BiLSTM Encoding
│  ├─ Forward LSTM: processes left-to-right
│  ├─ Backward LSTM: processes right-to-left
│  └─ Output: [batch_size, seq_len, 512] (combined hidden states)
│
├─ CRF Decoding Layer
│  ├─ Learns transition probabilities between entity tags
│  └─ Outputs: Most probable sequence of entity labels
│
└─ Output: BIO tags (Begin-Inside-Outside) for each token
   └─ Example: [B-DISEASE, I-DISEASE, O, B-PROCEDURE, O]
```

**Entity Types (Minimum):**
- DISEASE/DIAGNOSIS
- PROCEDURE
- MEDICATION
- SYMPTOM
- ANATOMICAL_LOCATION
- LAB_VALUE
- TEST_FINDING

**BERT Model Selection:**
- **ClinicalBERT** (Recommended): Pre-trained on MIMIC-III
- **BioBERT**: Pre-trained on biomedical literature
- **SciBERT**: Scientific text (alternative)

**Training Hyperparameters:**
```python
{
    "max_seq_length": 512,
    "batch_size": 32,
    "learning_rate": 5e-5,
    "epochs": 10-20,
    "optimizer": "AdamW",
    "dropout": 0.1,
    "lstm_hidden_size": 256,
    "lstm_layers": 2,
    "crf_transitions": True,
    "gradient_clip": 1.0
}
```

**Expected Performance:**
- Training on 1000 labeled documents: F1 ~0.82
- Training on 3000 labeled documents: F1 ~0.88
- Training on 5000+ labeled documents: F1 ~0.92+

**Inference Specifications:**
- Single chart processing: 50-200ms (GPU)
- Batch processing (100 charts): 2-5 seconds
- Throughput: 100-1000 charts/second (clustered)

---

### 1.2 Assertion Detection System

**Two-Layer Architecture:**

**Layer 1: Rule-Based Negation (Fast Path)**
```python
NEGATION_TRIGGERS = {
    "no": "negation",
    "not": "negation",
    "without": "negation",
    "denies": "negation",
    "denied": "negation",
    "ruled out": "negation",
    "r/o": "negation",
    "cannot": "negation",
    "did not": "negation"
}

UNCERTAINTY_TRIGGERS = {
    "possible": "suspected",
    "possibly": "suspected",
    "likely": "suspected",
    "probably": "suspected",
    "suggest": "suspected",
    "may": "suspected",
    "might": "suspected",
    "cannot rule out": "suspected",
    "rule out": "suspected",
    "pending": "conditional"
}

HISTORICAL_TRIGGERS = {
    "history of": "historical",
    "previously": "historical",
    "prior": "historical",
    "past medical": "historical",
    "former": "historical",
    "resolved": "historical",
    "healed": "historical"
}
```

**Algorithm:**
```python
def detect_negation(tokens, entity_start, entity_end):
    # Look backward from entity for negation triggers
    # Default scope: 10 tokens before entity, 5 tokens after
    scope_start = max(0, entity_start - 10)
    scope_text = " ".join(tokens[scope_start:entity_end + 5])
    
    for trigger in NEGATION_TRIGGERS:
        if trigger in scope_text.lower():
            # Verify trigger is before entity (not after)
            trigger_pos = scope_text.lower().find(trigger)
            entity_pos = 10 * len(tokens[scope_start])  # approximate
            if trigger_pos < entity_pos:
                return "Absent"
    
    return "Present"  # Default
```

**Layer 2: Deep Learning Assertion Classifier**

```python
class AssertionClassifier(nn.Module):
    def __init__(self):
        self.bert = ClinicalBERT.from_pretrained('clinical-bert-base')
        self.lstm = nn.LSTM(
            input_size=768,
            hidden_size=256,
            num_layers=2,
            bidirectional=True,
            batch_first=True
        )
        self.attention = AttentionLayer(512)  # bidirectional → 512
        self.classifier = nn.Linear(512, 7)  # 7 assertion types
    
    def forward(self, tokens, entity_span):
        # Encode clinical context
        embeddings = self.bert(tokens)
        lstm_out, _ = self.lstm(embeddings)
        
        # Attend to entity and surrounding context
        context = extract_context(lstm_out, entity_span, window=10)
        attended = self.attention(context)
        
        # Classify assertion type
        logits = self.classifier(attended)
        assertion = softmax(logits).argmax()
        confidence = softmax(logits).max()
        
        return ASSERTION_TYPES[assertion], confidence
```

**Assertion Classes (CMS Compliant):**
```python
ASSERTION_TYPES = [
    0: "Present",        # Code as HCC
    1: "Absent",         # Do NOT code
    2: "Suspected",      # Do NOT code
    3: "Conditional",    # Do NOT code (depends on future)
    4: "Associated_with",  # May code if meets criteria
    5: "Hypothetical",   # Do NOT code
    6: "Historical"      # Do NOT code (resolved)
]

# Decision logic
ASSERTION_DECISION = {
    "Present": True,           # CODE
    "Absent": False,           # DON'T CODE
    "Suspected": False,        # DON'T CODE (CMS rule)
    "Conditional": False,      # DON'T CODE
    "Associated_with": True,   # CODE (context-dependent)
    "Hypothetical": False,     # DON'T CODE
    "Historical": False        # DON'T CODE
}
```

**Performance Metrics:**
- Negation detection: 98% F1 score
- Scope recognition: 95% accuracy
- Combined assertion: 93% accuracy
- Inference time: 100-300ms per document

---

### 1.3 ICD-10 Code Prediction

**Multi-Label Classification Architecture**

```
Document Text
    ↓
[BERT Encoder]
    ↓ [1, 768] (document embedding)
    ↓
[Attention Layer] ← Learns which tokens matter for each code
    ↓ [num_icd_codes, 768]
    ↓
[Dense Layers × 2]
    ├─ Hidden: 1024 neurons
    ├─ Dropout: 0.2
    └─ ReLU activation
    ↓
[Output Layer]
    └─ sigmoid(logits) → confidence per code
    ↓
[Code Selection]
    ├─ Apply threshold (default 0.5)
    ├─ Filter by confidence
    └─ Match to extracted entities
    ↓
Output: [(code, confidence), ...]
```

**Implementation Details:**

```python
class ICD10MultiLabelClassifier(nn.Module):
    def __init__(self, num_icd_codes=71000):
        self.bert = ClinicalBERT.from_pretrained('clinical-bert-base')
        
        # Multi-head attention for code relevance
        self.attention_heads = nn.ModuleList([
            nn.Linear(768, 768) for _ in range(8)
        ])
        
        # Dense classification layers
        self.dense1 = nn.Linear(768, 1024)
        self.dropout = nn.Dropout(0.2)
        self.dense2 = nn.Linear(1024, 512)
        self.classifier = nn.Linear(512, num_icd_codes)
    
    def forward(self, input_ids, attention_mask):
        # Get document encoding
        outputs = self.bert(input_ids, attention_mask=attention_mask)
        doc_embedding = outputs.pooler_output  # [batch, 768]
        
        # Process through dense layers
        x = self.dense1(doc_embedding)
        x = nn.functional.relu(x)
        x = self.dropout(x)
        
        x = self.dense2(x)
        x = nn.functional.relu(x)
        x = self.dropout(x)
        
        # Multi-label prediction
        logits = self.classifier(x)
        confidences = torch.sigmoid(logits)
        
        return confidences

# Training loss: Binary Cross-Entropy (suitable for multi-label)
criterion = nn.BCEWithLogitsLoss()

# Inference: Select codes above threshold
def predict_codes(confidences, threshold=0.5, top_k=50):
    codes = []
    for idx, conf in enumerate(confidences[0]):
        if conf > threshold:
            codes.append((ICD10_CODES[idx], float(conf)))
    
    # Sort by confidence, return top K
    codes.sort(key=lambda x: x[1], reverse=True)
    return codes[:top_k]
```

**Handling Extreme Multi-Label Problem (71,000 codes):**

The challenge: Most documents use 5-20 codes; tail labels (rare codes) hard to predict.

**Solution 1: Hierarchical Approach**
- First predict code category (100-200 categories)
- Then predict specific codes within category
- Reduces search space significantly

**Solution 2: Extreme Multi-Label Learning**
- Use tree-based methods (PfastreXML, SLEEC)
- Partition label space into clusters
- Train separate classifiers per cluster

**Solution 3: Entity-Driven Filtering**
```python
def filter_codes_by_entities(predicted_codes, extracted_entities):
    """Only keep codes matching extracted medical entities"""
    filtered = []
    
    for code, confidence in predicted_codes:
        # Map code to ICD-10 description
        code_text = ICD10_DESCRIPTIONS[code].lower()
        
        # Check if any extracted entity matches code
        for entity_type, entity_text in extracted_entities:
            if entity_text.lower() in code_text:
                filtered.append((code, confidence))
                break
    
    return filtered
```

---

### 1.4 HCC Mapping and RAF Calculation

**HCC Mapping Algorithm**

```python
class HCCMapper:
    def __init__(self, model_version="V28"):
        # Load CMS Table 3 crosswalk
        self.icd_to_hcc = load_cms_table3(model_version)
        
        # Load HCC hierarchy (parent-child relationships)
        self.hcc_hierarchy = {
            "HCC19": None,  # Diabetes with complications (top)
            "HCC17": "HCC19",  # Diabetes without complications (child of HCC19)
            "HCC18": "HCC19"   # Diabetes with chronic kidney disease (child of HCC19)
        }
        
        # Load CMS coefficients for RAF
        self.hcc_coefficients = load_cms_coefficients(model_version)
        self.demographic_coeff = load_demographic_coefficients()
    
    def map_icd_to_hcc(self, icd_codes_with_confidence, assertions):
        """
        Convert ICD-10 codes to HCC codes, applying hierarchy rules
        """
        hcc_set = set()
        hcc_confidence = {}  # Track confidence for each HCC
        
        for icd_code, icd_conf in icd_codes_with_confidence:
            # Check assertion - skip if negated/uncertain
            assertion = assertions.get(icd_code, "Present")
            if assertion != "Present" and assertion != "Associated_with":
                continue
            
            # Get candidate HCCs for this ICD code
            candidate_hccs = self.icd_to_hcc.get(icd_code, [])
            
            for hcc in candidate_hccs:
                # Check if parent HCC already in set
                parent = self.hcc_hierarchy.get(hcc)
                if parent and parent in hcc_set:
                    # Parent already captured; skip child
                    continue
                
                # Check if any children would be removed
                should_add = True
                children_to_remove = []
                
                for existing_hcc in hcc_set:
                    existing_parent = self.hcc_hierarchy.get(existing_hcc)
                    if existing_parent == hcc:
                        # Found child; will be removed
                        children_to_remove.append(existing_hcc)
                
                # Remove children, add parent
                for child in children_to_remove:
                    hcc_set.remove(child)
                
                hcc_set.add(hcc)
                hcc_confidence[hcc] = icd_conf
        
        return sorted(list(hcc_set))
    
    def calculate_raf(self, hcc_codes, demographics):
        """
        Calculate Risk Adjustment Factor score
        
        demographics = {
            'age': 65,
            'gender': 'M',
            'medicaid': False,
            'disabled': False,
            'esrd': False,
            'institutional': False
        }
        """
        raf = 1.0  # Baseline
        
        # Add HCC coefficients
        for hcc in hcc_codes:
            coefficient = self.hcc_coefficients.get(hcc, 0.0)
            raf += coefficient
        
        # Add demographic adjustments
        demo_adj = self.calculate_demographic_adjustment(demographics)
        raf += demo_adj
        
        # Apply minimum/maximum bounds
        raf = max(raf, 0.5)  # Minimum floor
        raf = min(raf, 5.0)  # Reasonable maximum
        
        return raf
    
    def calculate_demographic_adjustment(self, demographics):
        """
        Apply age, gender, and status adjustments
        """
        adjustments = 0.0
        
        # Age adjustment (simplified)
        age = demographics['age']
        if age < 18:
            adjustments -= 0.1
        elif age > 85:
            adjustments += 0.15
        elif age > 75:
            adjustments += 0.08
        
        # Medicaid adjustment
        if demographics.get('medicaid'):
            adjustments += 0.05
        
        # Disability adjustment
        if demographics.get('disabled'):
            adjustments += 0.10
        
        # Institutional adjustment
        if demographics.get('institutional'):
            adjustments += 0.12
        
        return adjustments
```

**CMS Model Versions:**

```python
HCC_MODEL_VERSIONS = {
    "V24": {
        "num_hccs": 86,
        "crosswalk_file": "cms_table3_v24.xlsx",
        "coefficients_file": "hcc_coefficients_v24.csv",
        "years": [2018, 2019, 2020, 2021, 2022, 2023],
        "status": "Legacy"
    },
    "V28": {
        "num_hccs": 115,
        "crosswalk_file": "cms_table3_v28.xlsx",
        "coefficients_file": "hcc_coefficients_v28.csv",
        "years": [2024, 2025, 2026],
        "status": "Current"
    }
}
```

**Where to Get CMS Files:**
- CMS.gov: `https://www.cms.gov/medicare/payment/medicare-advantage-rates-statistics/risk-adjustment/`
- Table 3 ICD-10 Mappings: Annual update for each model year
- Coefficients: Published with annual rate announcements
- DIY Software: Complete mapping tables and validation logic

---

## Part 2: Data Pipeline Specifications

### 2.1 Input Data Format

**Source Documents (Priority Order):**
1. Discharge Summaries (highest quality, most structured)
2. Hospitalization Notes
3. Outpatient Visit Notes
4. Specialty Consultations
5. Lab/Imaging Reports
6. Progress Notes

**Structured Document Format:**
```json
{
  "patient_id": "PT123456",
  "date_of_service": "2024-03-15",
  "note_type": "discharge_summary",
  "clinical_text": "Patient admitted with...",
  "sections": {
    "chief_complaint": "...",
    "history_of_present_illness": "...",
    "past_medical_history": "...",
    "assessment_and_plan": "...",
    "hospital_course": "..."
  },
  "metadata": {
    "provider_npi": "1234567890",
    "facility_id": "FAC001",
    "admission_date": "2024-03-01",
    "discharge_date": "2024-03-15"
  }
}
```

**Important Preprocessing:**
- Remove Protected Health Information (PHI)
- Standardize text encoding (UTF-8)
- Remove formatting artifacts
- Preserve clinical abbreviations
- Keep section headers for context

---

### 2.2 Training Data Annotation Guidelines

**NER Annotation (Entity Extraction):**

**Annotation Standard:** BIO format (Begin-Inside-Outside)

```
Example text: "Patient has Type 2 diabetes and hypertension"

Annotation:
"Patient" → O (outside)
"has" → O
"Type" → B-DISEASE
"2" → I-DISEASE
"diabetes" → I-DISEASE
"and" → O
"hypertension" → B-DISEASE
```

**Quality Assurance:**
- Double annotation on 20% of data (calculate inter-annotator agreement)
- Cohen's kappa target: >0.80
- Reconciliation discussion for disagreements
- Document entity boundary rules

**Assertion Annotation:**

```
Format: Entity with assertion label

Example 1: (DISEASE:diabetes, ASSERTION:Present)
"Patient diagnosed with diabetes"

Example 2: (DISEASE:pneumonia, ASSERTION:Absent)
"Pneumonia ruled out"

Example 3: (DISEASE:heart_disease, ASSERTION:Historical)
"History of myocardial infarction 2015"

Example 4: (DISEASE:cancer, ASSERTION:Suspected)
"Possible malignancy pending biopsy"
```

**Labeling Cost Estimates:**
- NER annotation: 3-5 minutes per document
- Assertion annotation: 2-3 minutes per document
- Total per document: 5-8 minutes
- 500 documents: 40-60 hours
- 3000 documents: 250-400 hours
- 5000 documents: 400-660 hours

---

### 2.3 Data Quality Validation

**Validation Checklist:**
```python
def validate_training_data(documents):
    issues = []
    
    # Check 1: Missing fields
    for doc in documents:
        if not doc.get('clinical_text'):
            issues.append(f"Doc {doc['id']}: Missing clinical_text")
        if not doc.get('annotations'):
            issues.append(f"Doc {doc['id']}: Missing annotations")
    
    # Check 2: Annotation consistency
    for doc in documents:
        for annotation in doc['annotations']:
            entity_text = annotation['text']
            start, end = annotation['start'], annotation['end']
            
            # Verify text spans match
            actual_text = doc['clinical_text'][start:end]
            if actual_text != entity_text:
                issues.append(f"Span mismatch in doc {doc['id']}")
    
    # Check 3: Label distribution
    label_dist = Counter()
    for doc in documents:
        for ann in doc['annotations']:
            label_dist[ann['label']] += 1
    
    # Flag severe imbalance
    max_label = max(label_dist.values())
    for label, count in label_dist.items():
        if count < max_label * 0.01:  # <1% of max
            issues.append(f"Label {label} severely underrepresented ({count} samples)")
    
    return issues
```

---

## Part 3: Deployment Architecture

### 3.1 Production Inference Pipeline

**Containerized Service:**
```dockerfile
FROM pytorch/pytorch:2.0-cuda11.8-devel-ubuntu22.04

WORKDIR /app

# Install dependencies
RUN pip install torch transformers torch-crf spacy pandas numpy

# Copy model files
COPY models/ ./models/
COPY config.yaml ./

# Copy application code
COPY src/ ./src/

EXPOSE 8000

CMD ["python", "src/inference_server.py"]
```

**Service API Specification:**
```python
# FastAPI endpoints

@app.post("/predict/hcc")
async def predict_hcc(document: ClincalDocument):
    """
    Request:
    {
        "patient_id": "PT123",
        "clinical_text": "...",
        "date_of_service": "2024-03-15"
    }
    
    Response:
    {
        "patient_id": "PT123",
        "icd_codes": [
            {"code": "E11.65", "confidence": 0.94, "assertion": "Present"},
            ...
        ],
        "hcc_codes": [
            {"hcc": "HCC19", "icd_source": "E11.65", "confidence": 0.94},
            ...
        ],
        "raf_score": 1.35,
        "processing_time_ms": 245,
        "model_version": "v2.1",
        "confidence_threshold": 0.5
    }
    
    """
    
    # Preprocess
    tokens = preprocess(document.clinical_text)
    
    # Run NER
    entities = ner_model(tokens)
    
    # Detect assertions
    assertions = assertion_model(tokens, entities)
    
    # Predict ICD codes
    icd_codes = icd_classifier(document.clinical_text)
    
    # Filter by assertion
    valid_codes = [c for c in icd_codes if assertions[c[0]] in ["Present", "Associated_with"]]
    
    # Map to HCC
    hcc_codes = hcc_mapper.map_to_hcc(valid_codes, assertions)
    
    # Calculate RAF
    raf = hcc_mapper.calculate_raf(hcc_codes, patient_demographics)
    
    return response
```

**Performance Requirements:**
- Latency: <500ms per document (p95)
- Throughput: 100+ documents/second with 8 GPU instances
- Uptime: 99.9%
- Memory: <12GB per GPU with batch size 32

---

### 3.2 Scaling Architecture

**Kubernetes Deployment:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: hcc-nlp-inference
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: hcc-nlp
        image: hcc-nlp:v2.1
        resources:
          requests:
            gpu: "1"
            memory: "16Gi"
          limits:
            gpu: "1"
            memory: "20Gi"
        ports:
        - containerPort: 8000
      nodeSelector:
        node-type: gpu-enabled

---
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: hcc-nlp-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: hcc-nlp-inference
  minReplicas: 3
  maxReplicas: 20
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

---

### 3.3 Quality Assurance and Monitoring

**Continuous Monitoring Metrics:**
```python
class ModelMonitoring:
    def __init__(self):
        self.metrics = {
            'predictions_per_hour': 0,
            'avg_latency_ms': 0,
            'error_rate': 0.0,
            'confidence_distribution': [],
            'hcc_discovery_rate': 0.0,
            'manual_review_rate': 0.0
        }
    
    def track_prediction(self, document_id, prediction, latency_ms, manual_review):
        self.metrics['predictions_per_hour'] += 1
        self.metrics['avg_latency_ms'] = moving_average(latency_ms)
        
        if manual_review:
            self.metrics['manual_review_rate'] += 1
        
        # Track confidence distribution (alert on bimodal)
        self.metrics['confidence_distribution'].append(
            prediction['confidence_threshold']
        )
    
    def detect_degradation(self):
        """Alert if model performance degrading"""
        if self.metrics['error_rate'] > 0.05:
            alert("High error rate detected")
        
        if self.metrics['hcc_discovery_rate'] < 0.90:
            alert("HCC discovery rate below threshold")
        
        if self.metrics['avg_latency_ms'] > 1000:
            alert("Latency above SLA")

# Alert thresholds
ALERT_THRESHOLDS = {
    "error_rate": 0.05,  # 5%
    "hcc_discovery_rate": 0.90,  # 90%
    "latency_p95": 1000,  # 1 second
    "manual_review_rate": 0.10  # 10%
}
```

**Human-in-the-Loop Quality Gate:**
```python
def should_escalate_for_review(prediction, confidence_threshold=0.75):
    """Determine if prediction needs human review"""
    
    escalate_reasons = []
    
    # Check 1: Low confidence on primary HCC
    if prediction['hcc_codes']:
        primary_confidence = max(h['confidence'] for h in prediction['hcc_codes'])
        if primary_confidence < confidence_threshold:
            escalate_reasons.append(f"Low confidence: {primary_confidence:.2f}")
    
    # Check 2: Contradictory assertions
    assertions = [code['assertion'] for code in prediction['icd_codes']]
    if len(set(assertions)) > 2:  # Too many different assertions
        escalate_reasons.append("Contradictory assertions detected")
    
    # Check 3: Uncommon HCC codes (tail labels)
    for hcc in prediction['hcc_codes']:
        if is_rare_hcc(hcc['hcc']):
            escalate_reasons.append(f"Rare HCC: {hcc['hcc']}")
    
    # Check 4: Large document (more complex)
    token_count = len(prediction.get('tokens', []))
    if token_count > 2000:
        escalate_reasons.append("Long document (potential complexity)")
    
    return len(escalate_reasons) > 0, escalate_reasons
```

---

## Part 4: Integration and Testing

### 4.1 Integration with EHR Systems

**Common Integration Points:**

**1. Batch Processing (Nightly):**
```python
# Extract all notes from yesterday
notes = ehr_system.query(
    date_from="2024-03-14",
    date_to="2024-03-15",
    note_types=["discharge_summary", "hospitalization"]
)

# Process through NLP pipeline
results = []
for note in notes:
    prediction = hcc_nlp.predict(note)
    results.append(prediction)

# Store results
hcc_storage.batch_insert(results)

# Generate report
report = generate_coding_report(results)
notification.send_to_coders(report)
```

**2. Real-Time API Integration:**
```python
# EHR calls API during documentation review
response = requests.post(
    'https://hcc-nlp-api.internal/predict/hcc',
    json={
        'patient_id': patient_id,
        'clinical_text': note_text,
        'date_of_service': date_of_service
    }
)

# Display suggestions to clinician
suggestions = response.json()['icd_codes']
display_coding_suggestions(suggestions)
```

**3. Claim Submission Integration:**
```python
# Before claim submission, validate HCC codes
claim_data = {
    'patient_id': 'PT123',
    'icd_codes': ['E11.65', 'I10'],
    'hcc_codes': ['HCC19', 'HCC18']
}

# Get HCC validation
validation = hcc_validator.validate(claim_data)

if validation['valid']:
    billing.submit_claim(claim_data)
else:
    for error in validation['errors']:
        logging.warning(f"Claim validation error: {error}")
```

---

### 4.2 Testing Strategy

**Unit Tests:**
```python
def test_ner_basic():
    """Test NER on simple sentence"""
    text = "Patient has diabetes"
    entities = ner_model(text)
    assert len(entities) == 1
    assert entities[0]['label'] == 'DISEASE'
    assert 'diabetes' in entities[0]['text']

def test_negation_detection():
    """Test negation is properly detected"""
    text = "Patient denies hypertension"
    entities = ner_model(text)
    assertions = assertion_model(text, entities)
    assert assertions[entities[0]['id']] == 'Absent'

def test_icd_to_hcc_mapping():
    """Test ICD-10 to HCC mapping"""
    hcc_codes = hcc_mapper.map_to_hcc([('E11.65', 0.95)])
    assert 'HCC19' in hcc_codes

def test_raf_calculation():
    """Test RAF score calculation"""
    demographics = {'age': 65, 'gender': 'M', 'medicaid': False}
    raf = hcc_mapper.calculate_raf(['HCC19', 'HCC18'], demographics)
    assert 1.0 < raf < 3.0
```

**Integration Tests:**
```python
def test_end_to_end_pipeline():
    """Test full pipeline on real discharge summary"""
    note = load_test_note("discharge_summary_example.txt")
    
    prediction = hcc_nlp.predict(note)
    
    # Validate outputs
    assert 'icd_codes' in prediction
    assert 'hcc_codes' in prediction
    assert 'raf_score' in prediction
    
    # Check reasonable values
    assert len(prediction['icd_codes']) > 0
    assert len(prediction['hcc_codes']) > 0
    assert 0.5 < prediction['raf_score'] < 5.0

def test_batch_processing():
    """Test batch processing performance"""
    notes = load_test_notes(1000)
    
    start = time.time()
    predictions = hcc_nlp.batch_predict(notes)
    duration = time.time() - start
    
    assert len(predictions) == 1000
    assert duration < 120  # Must complete in 2 minutes
    assert duration / 1000 < 0.5  # <500ms per document average
```

---

## Part 5: Maintenance and Continuous Improvement

### 5.1 Monthly Maintenance Tasks

**Model Retraining Schedule:**
```python
# Weekly: Collect validated corrections
weekly_validated = collect_validated_corrections(
    date_from=last_monday,
    date_to=today
)

# Monthly: Full model retraining if sufficient data collected
if len(weekly_validated) > 500:
    # Combine with original training data
    new_training_data = original_training_data + weekly_validated
    
    # Split
    train, val = split(new_training_data, ratio=0.85)
    
    # Retrain
    new_model = train_ner_model(train)
    
    # Evaluate
    metrics = evaluate(new_model, val)
    
    if metrics['f1'] > current_model_f1:
        deploy_new_model(new_model)
        log_model_update(metrics)
```

**Performance Monitoring:**
```python
def monthly_performance_report():
    """Generate monthly performance report"""
    
    results = {
        'ner_f1_score': calculate_validation_f1(),
        'hcc_capture_rate': calculate_hcc_capture_rate(),
        'false_positive_rate': calculate_fp_rate(),
        'manual_review_rate': calculate_review_rate(),
        'processing_latency_p95': calculate_p95_latency(),
        'raf_score_variance': compare_raf_to_manual_coding(),
        'common_errors': identify_error_patterns(),
        'model_drift': detect_data_drift()
    }
    
    return results
```

---

### 5.2 Model Versioning and Rollback

**Version Control:**
```python
DEPLOYED_MODELS = {
    'v1.0': {
        'date': '2024-01-01',
        'ner_f1': 0.85,
        'hcc_capture': 0.92,
        'status': 'deprecated'
    },
    'v2.0': {
        'date': '2024-02-15',
        'ner_f1': 0.88,
        'hcc_capture': 0.95,
        'status': 'production'
    },
    'v2.1': {
        'date': '2024-03-20',
        'ner_f1': 0.89,
        'hcc_capture': 0.96,
        'status': 'testing'
    }
}

def rollback_to_previous_version():
    """Emergency rollback if new model degrades performance"""
    previous = get_previous_production_model()
    deploy_model(previous)
    alert("Rolled back to " + previous.version)
```

---

## Conclusion

This technical reference provides the specifications and code patterns for building production-grade NLP systems for HCC coding. Key success factors:

1. **Architecture**: BiLSTM-CRF NER + assertion detection + multi-label ICD classification
2. **Data**: 3000-5000 labeled documents for fine-tuning pre-trained models
3. **Quality**: Assertion handling most critical; impacts compliance
4. **Operations**: Continuous monitoring, monthly retraining, human review gates
5. **Deployment**: Containerized, auto-scaling, with fallback procedures

Expected performance: 95%+ HCC capture, <500ms latency, 10:1+ ROI within 6 months.

