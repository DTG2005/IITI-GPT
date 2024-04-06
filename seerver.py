# -*- coding: utf-8 -*-
"""Copy of AVA New Demo.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1EbnoN49eQ8Xr4w9XNc3UDRYdKsQxkMpa

# Convert Data to Embeds
"""

# !pip install transformers hnswlib sentence_transformers gradio

import numpy as np
import argparse
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse
from pydantic import BaseModel
from fastapi import Response
from transformers import AutoTokenizer
# import hnswlib
from sentence_transformers import SentenceTransformer
import pandas as pd
import os
import json
import re
from sentence_transformers import SentenceTransformer, CrossEncoder
# import hnswlib
import numpy as np
from typing import Iterator
import faiss
from streamtry import tts, stream_ffplay, argparse

import gradio as gr
from gradio_client import Client
import pandas as pd
import torch

from transformers import AutoTokenizer, AutoModelForCausalLM, TextIteratorStreamer ,BitsAndBytesConfig
from transformers import AutoTokenizer
import os
from threading import Thread
# url = 'https://huggingface.co/spaces/Warlord-K/IITI-Similarity/resolve/main/iiti.txt'
# data = wget.download(url)
# !wget -O data.txt https://huggingface.co/spaces/Warlord-K/IITI-Similarity/resolve/main/iiti.txt

class GenerateRequest(BaseModel):
    base_prompt: str
    history: list



def read_text_from_file(file_path):
    with open(file_path, "r") as text_file:
        text = text_file.read()
    texts = text.split("&&")
    return [t.strip() for t in texts]

def create_hnsw_index(embeddings_file, M=16, efC=100):
    embeddings = np.load(embeddings_file)
    # Create the HNSW index
    num_dim = embeddings.shape[1]
    ids = np.arange(embeddings.shape[0])
    index = hnswlib.Index(space="ip", dim=num_dim)
    index.init_index(max_elements=embeddings.shape[0], ef_construction=efC, M=M)
    index.add_items(embeddings, ids)
    return index

text_file_path = "data.txt"
texts = read_text_from_file(text_file_path)
speaker = None
with open("./default_speaker.json", "r") as file:
    speaker = json.load(file)


groq_key = "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"

biencoder = SentenceTransformer("sentence-transformers/multi-qa-MiniLM-L6-cos-v1", device="cuda")
cross_encoder = CrossEncoder("BAAI/bge-reranker-base", max_length=512, device="cuda")

# embeddings = biencoder.encode(texts, normalize_embeddings=True)
# np.save('embeddings.npy',embeddings)

# index = create_hnsw_index('embeddings.npy')
# index.save_index('search_index.bin')

# index = faiss.IndexFlatL2(embeddings.shape[1])
# index.add(embeddings)

df = pd.DataFrame(texts, columns = ["chunk_content"])

df.head()

df.to_parquet("chunked_data.parquet")

"""#FINAL INFERENCE"""

# Commented out IPython magic to ensure Python compatibility.
# %%capture
# !pip install transformers hnswlib sentence_transformers gradio bitsandbytes accelerate


MAX_MAX_NEW_TOKENS = 250
DEFAULT_MAX_NEW_TOKENS = 250
MAX_INPUT_TOKEN_LENGTH = 4000
EMBED_DIM = 1024
K = 3
EF = 100
TEXT_FILE = 'data.txt'
SEARCH_INDEX = "search_index.bin"
EMBEDDINGS_FILE = "embeddings.npy"
DOCUMENT_DATASET = "chunked_data.parquet"
COSINE_THRESHOLD = 0.3


torch_device = "cuda" if torch.cuda.is_available() else "cpu"
print("Running on device:", torch_device)
print("CPU threads:", torch.get_num_threads())

model_name = "Intel/neural-chat-7b-v3-1"

bnb_4bit_compute_dtype = "float16"
compute_dtype = getattr(torch, bnb_4bit_compute_dtype)
# Activate 4-bit precision base model loading
use_4bit = True

# Compute dtype for 4-bit base models

# Quantization type (fp4 or nf4)
bnb_4bit_quant_type = "nf4"

# Activate nested quantization for 4-bit base models (double quantization)
use_nested_quant = False
bnb_config = BitsAndBytesConfig(
    load_in_4bit=use_4bit,
    bnb_4bit_quant_type=bnb_4bit_quant_type,
    bnb_4bit_compute_dtype=compute_dtype,
    bnb_4bit_use_double_quant=use_nested_quant,
)

tokenizer = AutoTokenizer.from_pretrained("Intel/neural-chat-7b-v3-1", trust_remote_code=False, cache_dir = "hf_cache")
model = AutoModelForCausalLM.from_pretrained(
    model_name,
    # torch_dtype=torch.float16,
    quantization_config=bnb_config,
    device_map="auto"
)
streamer = TextIteratorStreamer(tokenizer, skip_prompt=True)
def read_text_from_file(file_path):
    with open(file_path, "r", encoding="utf-8") as text_file:
        text = text_file.read()
    texts = text.split("&&")
    texts = [text for text in texts if text]
    return [t.strip() for t in texts]

def create_qa_prompt(query, relevant_chunks):
    stuffed_context = " ".join(relevant_chunks)
    return f'''### System:\nYou are IITI-GPT, a helpful chatbot which gives correct and truthful answers for IIT Indore.\n### User: Use the following pieces of context given in to answer the question at the end.
    If you don't know the answer, just say that you don't know, don't try to make up an answer. Keep the answer short and succinct. \nContext: {stuffed_context}
Question: {query}\n### Assistant:\n'''


def create_condense_question_prompt(question, chat_history):
    return f'''### System:\nYou are AVA, a helpful chatbot which gives correct and truthful answers for IIT Indore.\n### User:\n{question}\n### Assistant:\n'''
#     return f"""\
# Given the following conversation and a follow up question, \
# rephrase the follow up question to be a standalone question in its original language. \
# Output the json object with single field `question` and value being the rephrased standalone question.
# Only output json object and nothing else.
# Chat History:
# {chat_history}
# Follow Up Input: {question}
# """

def get_prompt(message: str, chat_history: list[tuple[str, str]], system_prompt: str) -> str:
    texts = [f"### System:\n{system_prompt}\n"]
    # The first user input is _not_ stripped
    do_strip = False
    for user_input, response in chat_history:
        user_input = user_input.strip() if do_strip else user_input
        do_strip = True
        texts.append(f"### User:\n{user_input}\n### Assistant:\n{response.strip()}")
    message = message.strip() if do_strip else message
    texts.append(f"### User:\n{message}\n### Assistant:\n")
    return "".join(texts)


def get_input_token_length(message: str, chat_history: list[tuple[str, str]], system_prompt: str) -> int:
    prompt = get_prompt(message, chat_history, system_prompt)
    input_ids = tokenizer([prompt], return_tensors="np", add_special_tokens=False)["input_ids"]
    return input_ids.shape[-1]
# def prompt_builder(prompt,system_message="You are a helpful chatbot which gives correct and truthful answers"):
#     prompt = f"<|system|>\n{system_message}</s>\n<|user|>\n{prompt}</s>\n<|assistant|>\n"
#     return prompt
def prompt_builder(prompt, system_message="You are a helpful chatbot which gives correct and truthful answers"):
  return f'''### System:\n{system_message}\n### User:\n{prompt}\n### Assistant:\n'''



def get_completion_condense(
    prompt,
    system_prompt=None,
    # model=model,
    max_new_tokens=512,
    temperature=0.2,
    top_p=0.95,
    top_k=50,
    is_streaming=False,
    debug=False):

    prompt_f = prompt_builder(prompt)
    # start_time = time.time()
    inputs = tokenizer.encode(prompt_f, return_tensors="pt", add_special_tokens=False)
    generation_kwargs = dict(inputs = inputs.to("cuda"), streamer=streamer, max_length=2000)
    # Generate a response
    thread = Thread(target=model.generate, kwargs=generation_kwargs)
    thread.start()
    generated_text = ""
    for new_text in streamer:
        generated_text += new_text
        # print(generated_text, flush=True, sep = '')
        output_file = 'out.wav'
        yield stream_ffplay(tts(args.new_text), args.output_file, save=True)


def get_completion(
    prompt,
    system_prompt=None,
    # model=model,
    max_new_tokens=512,
    temperature=0.2,
    top_p=0.95,
    top_k=50,
    is_streaming=False,
    debug=False):

    prompt_f = prompt_builder(prompt)
    # start_time = time.time()
    inputs = tokenizer.encode(prompt, return_tensors="pt", add_special_tokens=False)
    generation_kwargs = dict(inputs = inputs.to("cuda"), streamer=streamer, max_length=2000)
    # Generate a response
    thread = Thread(target=model.generate, kwargs=generation_kwargs)
    thread.start()
    generated_text = ""
    for new_text in streamer:
        generated_text += new_text
        yield new_text



# load the index for the data
def load_hnsw_index(index_file):
    # Load the HNSW index from the specified file
    index = hnswlib.Index(space="ip", dim=EMBED_DIM)
    index.load_index(index_file)
    return index


# create the index for the data from numpy embeddings
# avoid the arch mismatches when creating search index
def create_hnsw_index(embeddings_file, M=16, efC=100):
    embeddings = np.load(embeddings_file)
    # Create the HNSW index
    num_dim = embeddings.shape[1]
    ids = np.arange(embeddings.shape[0])
    index = hnswlib.Index(space="ip", dim=num_dim)
    index.init_index(max_elements=embeddings.shape[0], ef_construction=efC, M=M)
    index.add_items(embeddings, ids)
    return index


def create_query_embedding(query):
    # Encode the query to get its embedding
    embedding = biencoder.encode(list(query), normalize_embeddings=True)[0]
    return embedding


def find_nearest_neighbors(query_embedding):
    # search_index.set_ef(EF)
    # # Find the k-nearest neighbors for the query embedding
    # labels, distances = search_index.knn_query(query_embedding, k=K)
    # labels = [label for label, distance in zip(labels[0], distances[0]) if (1 - distance) >= COSINE_THRESHOLD]
    # relevant_chunks = data_df.iloc[labels]["chunk_content"].tolist()
    # return relevant_chunks

    # query_vector = np.asarray(embed_query(query))
    # query_vector=np.expand_dims(query_vector,axis=0)
    # print(query_vector.shape)
    # k = 3 # Number of nearest neighbors to retrieve
    D, I = index.search(np.expand_dims(np.asarray(query_embedding), axis=0), K)
    relevant_paragraph=[]
    for i in range(K):
        relevant_paragraph_index = I[0][i]
        relevant_paragraph.append(texts[relevant_paragraph_index])
    return relevant_paragraph


def rerank_chunks_with_cross_encoder(query, chunks):
    # Create a list of tuples, each containing a query-chunk pair
    pairs = [(query, chunk) for chunk in chunks]

    # Get scores for each query-chunk pair using the cross encoder
    scores = cross_encoder.predict(pairs)

    # Sort the chunks based on their scores in descending order
    sorted_chunks = [chunk for _, chunk in sorted(zip(scores, chunks), reverse=True)]

    return sorted_chunks


def generate_condensed_query(query, history):
    chat_history = ""
    for turn in history:
        chat_history += f"Human: {turn[0]}\n"
        chat_history += f"Assistant: {turn[1]}\n"

    condense_question_prompt = create_condense_question_prompt(query, chat_history)
    #print("Generate condense query called", condense_question_prompt)
    #condensed_question_list=[]
    #condensed_question_list.append(json.loads(get_completion(condense_question_prompt, max_new_tokens=64, temperature=0)))
    # Call get_completion and receive the list of chunks
    #condensed_question_list = get_completion_condense(condense_question_prompt, max_new_tokens=64, temperature=0)

    # Join the list elements into a single string if needed
    condensed_question = "".join(json.loads(get_completion_condense(condense_question_prompt, max_new_tokens=64, temperature=0)))

    #print(condensed_question_list)
    print(condensed_question)

    return condensed_question


DEFAULT_SYSTEM_PROMPT = """\
You are a helpful, respectful and honest assistant. Always answer as helpfully as possible, while being safe.  Your answers should not include any harmful, unethical, racist, sexist, toxic, dangerous, or illegal content. Please ensure that your responses are socially unbiased and positive in nature.
If a question does not make any sense, or is not factually coherent, explain why instead of answering something not correct. If you don't know the answer to a question, please don't share false information.\
"""
# MAX_MAX_NEW_TOKENS = 2048
# DEFAULT_MAX_NEW_TOKENS = 1024
# MAX_INPUT_TOKEN_LENGTH = 4000

DESCRIPTION = """
# AVA Southampton Chatbot 🤗
"""

LICENSE = """
<p/>
---
"""

if not torch.cuda.is_available():
    DESCRIPTION += "\n<p>Running on CPU 🥶.</p>"


def clear_and_save_textbox(message: str) -> tuple[str, str]:
    return "", message


def display_input(message: str, history: list[tuple[str, str]]) -> list[tuple[str, str]]:
    history.append((message, ""))
    return history


def delete_prev_fn(history: list[tuple[str, str]]) -> tuple[list[tuple[str, str]], str]:
    try:
        message, _ = history.pop()
    except IndexError:
        message = ""
    return history, message or ""

# requirements
parser = argparse.ArgumentParser()
args = parser.parse_args()


def generate(
    message: str,
    history_with_input: list[tuple[str, str]],
    system_prompt: str,
    max_new_tokens: int,
    temperature: float,
    top_p: float,
    top_k: int,
) -> Iterator[list[tuple[str, str]]]:
    if max_new_tokens > MAX_MAX_NEW_TOKENS:
        raise ValueError
    history = history_with_input[:-1]
    if len(history) > 0:
        try:
            condensed_query = generate_condensed_query(message, history)
        except Exception as e:

            condensed_query = message
        print(f"{condensed_query=}")
    else:
        condensed_query = message
        print(f"{condensed_query=}")
    # query_embedding = create_query_embedding(condensed_query)
    relevant_chunks = question(condensed_query)
    print(len(relevant_chunks))
    reranked_relevant_chunks = [""]
    if relevant_chunks:
        reranked_relevant_chunks = rerank_chunks_with_cross_encoder(condensed_query, relevant_chunks)
    print((reranked_relevant_chunks))
    qa_prompt = create_qa_prompt(condensed_query, reranked_relevant_chunks)
    # print(qa_prompt)
    try:
        generator = get_completion(
            qa_prompt,
            system_prompt=system_prompt,
            is_streaming=True,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_k=top_k,
            top_p=top_p,
        )

        output = ""
        for idx, response in enumerate(generator):
            token = response
            output += token

            if idx == 0:
                history.append((message, output))
            else:
                history[-1] = (message, output)
            # yield history
    except Exception as e:
        print(e)
    audio = stream_ffplay(
        tts(
            text=output.replace("IITI", "I I T I"),
            speaker= speaker,
            language="en",
            server_url="http://0.0.0.0:8000",
            stream_chunk_size="100"
        ),
        output_file="output.wav"
    )
    print(output)
    return history


def process_example(message: str) -> tuple[str, list[tuple[str, str]]]:
    generator = generate(message, [], DEFAULT_SYSTEM_PROMPT, 1024, 0.2, 0.95, 50)
    for x in generator:
        pass
    return "", x


def check_input_token_length(message: str, chat_history: list[tuple[str, str]], system_prompt: str) -> None:
    input_token_length = get_input_token_length(message, chat_history, system_prompt)
    if input_token_length > MAX_INPUT_TOKEN_LENGTH:
        raise gr.Error(
            f"The accumulated input is too long ({input_token_length} > {MAX_INPUT_TOKEN_LENGTH}). Clear your chat history and try again."
        )

if not os.path.exists(TEXT_FILE):
    os.system(f"wget -O {TEXT_FILE} https://huggingface.co/spaces/Slycat/Southampton-Similarity/resolve/main/Southampton.txt")
    
if not os.path.exists(EMBEDDINGS_FILE):
    texts = read_text_from_file(TEXT_FILE)
    embeddings = biencoder.encode(texts)
    np.save(EMBEDDINGS_FILE,embeddings)

embeddings = np.load(EMBEDDINGS_FILE)
d = embeddings.shape[1]  # Dimension of vectors
# print(doc_emb.shape)
index = faiss.IndexFlatL2(d)
index.add(embeddings)

def embed_query(query):
    query_emb = biencoder.encode(query)
    return query_emb

def question(query):
  query_vector = np.asarray(embed_query(query))
  query_vector=np.expand_dims(query_vector,axis=0)
  print(query_vector.shape)
  k = 3 # Number of nearest neighbors to retrieve
  D, I = index.search(query_vector, k)
  relevant_paragraph=[]
  for i in range(k):
    relevant_paragraph_index = I[0][i]
    relevant_paragraph.append(texts[relevant_paragraph_index])

  return relevant_paragraph

app=FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods = ["POST", "OPTIONS"],
    allow_headers = ["*"],
)

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.post("/query")
async def api(generateRequest : GenerateRequest):
    base_prompt = generateRequest.base_prompt
    history = generateRequest.history
    print("Hello2")
    os.system('rm output.wav | true')
    generate(
        message=base_prompt,
        history_with_input=history,
        system_prompt=DEFAULT_SYSTEM_PROMPT,
        max_new_tokens=MAX_MAX_NEW_TOKENS,
        temperature=0.2,
        top_p=0.95,
        top_k=50
    )
    print("Hello1")
    return FileResponse("output.wav")

if __name__ == '__main__':
    uvicorn.run(app, port=7000, host = '0.0.0.0')