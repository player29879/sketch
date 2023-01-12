# sketch

Co-pilot for pandas users, AI that understands the content of data, greatly enhancing the relevance of suggestions. Adding data context to AI code-writing assistants, usable in any Jupyter in seconds.

Enhance your workflow by asking questions of your data, and getting code suggestions to answer those questions. Reduce the time spent googling, asking chat-gpt3, and even re-writing co-pilot suggestions. Get more accurate code suggestions for code and pandas, all without adding any plugin to your IDE.

```bash
pip install sketch
```

## Demo 

https://user-images.githubusercontent.com/916073/211990122-21c90ddb-8eb7-4288-b2cf-1314e7796504.mp4

## How to use

It's as simple as importing sketch, and then using the `.sketch` extension on any pandas dataframe.

```python
import sketch
```

Now, any pandas dataframe you have will have an extension registered to it. Access this new extension with your dataframes name `.sketch`

### `.sketch.ask`

Ask is a basic question-answer system on sketch, this will return an answer in text that is based off of the summary statistics and description of the data. 

Use ask to get an understanding of the data, get better column names, ask hypotheticals (how would I go about doing X with this data), and more.

```python
df.sketch.ask("Which columns are integer type?")
```

### `.sketch.howto`

Howto is the basic "code-writing" prompt in sketch. This will return a code-block you should be able to copy paste and use as a starting point (or possibly ending!) for any question you have to ask of the data. Ask this how to clean the data, normalize, create new features, plot, and even build models!

```python
df.sketch.howto("Plot the sales versus time")
```

### `.sketch.apply`

apply is a more advanced prompt that is more useful for data generation. Use it to parse fields, generate new features, and more. This is built directly on [lambdaprompt](https://github.com/approximatelabs/lambdaprompt). In order to use this, you will need to set up a free account with OpenAI, and set an environment variable with your API key. `OPENAI_API_KEY=YOUR_API_KEY`

```python
df['review_keywords'] = df.sketch.apply("Keywords for the review [{{ review_text }}] of product [{{ product_name }}] (comma separated):")
```

```python
df['capitol'] = pd.DataFrame({'State': ['Colorado', 'Kansas', 'California', 'New York']}).sketch.apply("What is the capitol of [{{ State }}]?")
```

## Sketch currently uses `prompts.approx.dev` to help run with minimal setup

In the future, we plan to update the prompts at this endpoint with our own custom foundation model, built to answer questions more accurately than GPT-3 can with its minimal data context. 

You can also directly call OpenAI directly (and not use our endpoint) by using your own API key. To do this, set 2 environment variables.

(1) `SKETCH_USE_REMOTE_LAMBDAPROMPT=False`
(2) `OPENAI_API_KEY=YOUR_API_KEY`

## How it works

Sketch uses efficient approximation algorithms (data sketches) to quickly summarize your data, and feed that information into language models. Right now it does this by summarizing the columns and writing these summary statistics as additional context to be used by the code-writing prompt. In the future we hope to feed these sketches directly into custom made "data + language" foundation models to get more accurate results.

