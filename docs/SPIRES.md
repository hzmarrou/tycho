arXiv:2304.02711v2 [cs.AI] 22 Dec 2023

# STRUCTURED PROMPT INTERROGATION AND RECURSIVE EXTRACTION OF SEMANTICS (SPIRES): A METHOD FOR POPULATING KNOWLEDGE BASES USING ZERO-SHOT LEARNING

**J. Harry Caufield<sup>1</sup>, Harshad Hegde<sup>1</sup>, Vincent Emonet<sup>2</sup>, Nomi L. Harris<sup>1</sup>, Marcin Joachimiak<sup>1</sup>, Nicolas Matentzoglu<sup>3</sup>, HyeongSik Kim<sup>4</sup>, Sierra Moxon<sup>1</sup>, Justin T. Reese<sup>1</sup>, Melissa A. Haendel<sup>5</sup>, Peter N. Robinson<sup>6</sup>, and Christopher J. Mungall<sup>1</sup>**

<sup>1</sup>Division of Environmental Genomics and Systems Biology, Lawrence Berkeley National Laboratory, Berkeley, CA 94720, USA
<sup>2</sup>Institute of Data Science, Faculty of Science and Engineering, Maastricht University, Maastricht, The Netherlands
<sup>3</sup>Semanticly Ltd, Athens, Greece
<sup>4</sup>Robert Bosch LLC, Sunnyvale, CA 94085, USA
<sup>5</sup>Anschutz Medical Campus, University of Colorado, Aurora, CO 80217, USA
<sup>6</sup>The Jackson Laboratory for Genomic Medicine, Farmington, CT 06032, USA

December 22, 2023

### ABSTRACT

Creating knowledge bases and ontologies is a time consuming task that relies on manual curation. AI/NLP approaches can assist expert curators in populating these knowledge bases, but current approaches rely on extensive training data, and are not able to populate arbitrarily complex nested knowledge schemas.

Here we present Structured Prompt Interrogation and Recursive Extraction of Semantics (SPIRES), a Knowledge Extraction approach that relies on the ability of Large Language Models (LLMs) to perform zero-shot learning (ZSL) and general-purpose query answering from flexible prompts and return information conforming to a specified schema. Given a detailed, user-defined knowledge schema and an input text, SPIRES recursively performs prompt interrogation against an LLM to obtain a set of responses matching the provided schema. SPIRES uses existing ontologies and vocabularies to provide identifiers for matched elements.

We present examples of applying SPIRES in different domains, including extraction of food recipes, multi-species cellular signaling pathways, disease treatments, multi-step drug mechanisms, and chemical to disease orange relationships. Current SPIRES accuracy is comparable to the mid-range of existing Relation Extraction (RE) methods, but greatly surpasses an LLM’s native capability of grounding entities with unique identifiers. SPIRES has the advantage of easy customization, flexibility, and, crucially, the ability to perform new tasks in the absence of any new training data. This method supports a general strategy of leveraging the language interpreting capabilities of LLMs to assemble knowledge bases, assisting manual knowledge curation and acquisition while supporting validation with publicly-available databases and ontologies external to the LLM.

SPIRES is available as part of the open source OntoGPT package: https://github.com/monarch-initiative/ontogpt.

**Contact:** jhc@lbl.gov

SPIRES

# 1 Introduction

Knowledge Bases and ontologies (here collectively referred to as KBs) encode domain knowledge in a structure that is amenable to precise querying and reasoning. General purpose KBs such as Wikidata [1] contain broad contextual knowledge, and are used for a wide variety of tasks, such as integrative analyses of otherwise disconnected data and enrichment of web applications (for example, a recipe website may want to dynamically query Wikidata to retrieve information about ingredients or country of origin). In the life sciences, KBs such as the Gene Ontology (GO) [2] and the Reactome biological pathway KB [3] contain extensive curated knowledge detailing cellular mechanisms that involve interacting gene products and molecules. These domain-specific KBs are used for tasks such as interpreting high-throughput experimental data. All KBs, whether general purpose or domain-specific, owe their existence to curation, often a concerted effort by human experts.

However, the vast majority of human knowledge is communicated via natural language, with scientific knowledge communicated textually in journal abstracts and articles, which has historically been largely opaque to machines. The latest Natural Language Processing (NLP) techniques making use of Large Language Models (LLMs) have shown great promise in interpreting highly technical language, as demonstrated by orange their performance on question-answering benchmarks [4]. These techniques have known limitations, such as being prone to hallucinations [5] (i.e., generating incorrect statements) and insensitivity to negations [6]. Applications such as clinical decision support require precision and reliability not yet demonstrated by LMs of any size, though recent demonstrations offer promise [7, 8, 9, 10].

If instead of passing the unfiltered results of LLM queries to users, we use LLMs to build KBs using NLP at the time of KB construction, then we can assist manual knowledge curation and acquisition while validating facts prior to insertion into the KB. NLP can assist KB construction at multiple stages. Literature triage aids selection of relevant texts to curate; Named Entity Recognition (NER) can identify textual spans mentioning relevant things or concepts such as genes or ingredients; grounding maps these spans to persistent identifiers in databases or ontologies; Relation Extraction (RE) connects named entities via predicates such as ‘causes’ into simple triple statements. Deep Learning methods such as autoregressive LMs [11] have made considerable gains in all these areas. The first generation of these methods relied heavily on task-specific training data, but the latest generation of LLMs such as GPT-3 and GPT-4 are able to generalize and perform zero-shot or few-shot learning on these tasks by reframing them as prompt-completion tasks [12].

Most KBs are built upon detailed knowledge schemas which prove challenging to populate. Schemas describe the forms in which data should be structured within a domain. For example, a food recipe KB may break a recipe down into a sequence of dependent steps, where each step is a complex knowledge structure involving an action, utensils, and quantified inputs and outputs. Inputs and outputs might be a tuple of a food type plus a state (e.g. cooked) (Figure 1). Ontologies such as FOODON [7] may be used to provide identifiers for any named entities. Similarly, a biological pathway database might break down a cellular program into subprocesses and further into individual steps, each step involving actions, subcellular locations, and inputs and outputs with activation states and stoichiometry. Adapting existing pipelines to custom KB schemas requires considerable engineering.

A schema provides a structure for data. For example, the recipe schema in Figure 1 could be used in a recipe database, with each record instantiating the recipe class, with additional linked records instantiating contained classes, e.g. individual ingredients or steps. Figure 2 shows an example of an instantiated schema class, rendered using YAML [13] syntax.

Here we present Structured Prompt Interrogation and Recursive Extraction of Semantics (SPIRES), an automated approach for population of custom schemas and ontology models. The objective of SPIRES is to generate an instance (i.e., an object) from a text, where that instance has a collection of attribute-value associations. Each value is either a primitive (e.g. string, number, or identifier) or another inlined instance (Figure 2). SPIRES integrates the flexibility of LLMs with the reliability of publicly-available databases and ontologies (Figure 3). This strategy allows SPIRES to fill out schemas with linked data while bypassing a need for training examples. A major advantage of SPIRES over more traditional RE is its ability to populate schemas that exhibit nesting, in which complex classes may have attributes whose ranges are themselves complex classes. SPIRES also makes use of a flexible grounding approach that can leverage over a thousand ontologies in the OntoPortal Alliance [17], as well as biomedical lexical grounders such as Gilda [18] and OGER [19]. This grounding method offers far more consistent mapping to unique identifiers than hallucination-prone LLM querying alone.

# 2 System and Methods

In SPIRES, A knowledge *schema* is a structure for constraining the shape of instances for a given domain. A schema is a collection of *classes* or *templates*, each of which can be instantiated by instances. Each class has a collection of *attribute constraints*, which control the attribute-value pairs that can be associated with each instance. The range of an

2

SPIRES

```mermaid
erDiagram
    Recipe ||--o{ Step : steps
    Recipe ||--o{ Ingredient : ingredients
    Recipe ||--o{ RecipeCategory : categories
    Step ||--o{ UtensilType : utensils
    Step ||--o{ FoodItem : inputs
    Step ||--o{ FoodItem : outputs
    Step ||--o{ Action : action
    Ingredient ||--o{ FoodItem : food_item
    Ingredient ||--o{ Quantity : amount
    FoodItem ||--o{ FoodType : food
    Quantity ||--o{ Unit : unit

    Recipe {
        string label
        string description
    }
    RecipeCategory {
        string id
        string label
    }
    Step {
    }
    UtensilType {
        string id
        string label
    }
    FoodItem {
        string state
    }
    FoodType {
        string id
        string label
    }
    Action {
        string id
        string label
    }
    Ingredient {
    }
    Quantity {
        string value
    }
    Unit {
        string id
        string label
    }
```

Figure 1: Example schema. Boxes denote classes and arrows denote attributes whose range are classes (compound attributes). Crows feet above boxes denote multivalued attributes. Attributes whose ranges are primitives or value sets are shown within each box. Here, the top level container class "Recipe" is composed of a label, description, categories, steps, and ingredients. Steps and ingredients are further decomposed into food items, quantities, etc.

attribute specifies the allowed value or values. A range can be either (1) a primitive type such as a string or number; (2) a class; or (3) an *enumeration* of permissible value tokens (e.g., an enumeration of days of the week may include "Monday", "Tuesday", and so on). Attributes also have *cardinality*, specifying the minimum and maximum number of values each instance can take. Additionally, each schema element can have arbitrary metadata associated with it.

Formally, a schema $S$ consists of $n$ classes:

$$Classes(S) = \{c_1, \dots, c_n\}$$ (1)

Classes correspond to the kinds of entities present in a database (e.g. in a recipe database, this would include recipes, as well as ingredients and steps; see example in Figure 1).

Each class $c_i$ has an ordered list of attributes:

$$Attributes(c_i) = \{c_i a_1, \dots, c_i a_m\}$$ (2)

Instances of $c_i$ may have *values* specified for each of these attributes. An attribute $a$ can have associated properties:

* $Name(a)$ : the name of the attribute; for example, "summary" or "steps".
* $Multivalued(a) = \{True, False\}$, indicating whether the value of a is a list, or single-valued. A recipe might have a single-valued attribute for the name of the recipe, and a multivalued attribute for the steps.

3

SPIRES

*On medium heat melt the butter and sautee the onion and bell peppers. Add the hamburger meat and cook until meat is well done... Ingredients: 1 small onion, 2 bell peppers, 2 tablespoons garlic powder...*

```yaml
label: Simple Spaghetti
description: A tomato sauce spaghetti dish with hamburger meat and vegetables.
category:
  - dbpedia:Main_course             ## dbpedia ontology
  - dbpedia:Italian_cuisine         ## dbpedia ontology
ingredients:
  - food_item: FOODON:03301704      ## onion (whole, raw)
    quantity: 1
  - food_item: FOODON:00003485      ## sweet red bell pepper (whole)
    quantity: 2
  - food_item: FOODON:03301844      ## garlic powder
    quantity: 2
    unit: "[tbs_us]"                ## UCUM standard
  - food_item: FOODON:03310351      ## butter
    quantity: 3
    unit: "[tbs_us]"
  - food_item: FOODON:00001649      ## black or white pepper product
    quantity: 1
    unit: "[tbs_us]"
...
steps:
  - action: chop
    inputs:
      - FOODON:03301704             ## onion (whole, raw)
    outputs:
      - _:ChoppedOnion              ## (no term in ontology)
  - action: chop
    inputs:
      - FOODON:00003485             ## sweet red bell pepper (whole)
    outputs:
      - _:ChoppedBellPepper         ## (no term in ontology)
...
...
  - action: add
    inputs:
      - FOODON:03301217             ## tomato sauce
      - FOODON:00002221             ## salt product
      - FOODON:00001649             ## black or white pepper product
      - FOODON:03301644             ## garlic powder
    outputs:
      - FOODON:03304014             ## spaghetti sauce with meat
...
```

Figure 2: Example of a portion of text to parse and a corresponding instantiation of the recipe schema from Figure 1, using YAML syntax. Input text is truncated for brevity; the full input is available at https://github.com/monarch-initiative/ontogpt/blob/main/tests/input/cases/recipe-spaghetti.txt. In each attribute-value pair, the attribute is shown in **bold**, followed by a colon and then the value or values. For multivalued attributes, each list element value is indicated with a hyphen at the beginning of the line. Terminal elements that are value sets from ontologies and standards such as FOODON [14], UCUM [15], and DBPedia [16] are shown here with their human-readable labels in blue after the double-hash comment symbol. Dynamic elements are indicated via RDF blank node syntax (e.g. `_:ChoppedOnion` does not correspond to a named entity and serves as a placeholder.

* *Identifier(a)* = {*True, False*}, indicating whether *a* is a persistent identifier for instances, such as the FOODON identifiers in Figure 2.

* *Prompt(a)* = string, which is a user-specified custom prompt for that attribute.

* *Range(a)*: the allowable values for this attribute; this can be a class *c* in *S*, or a primitive type such as string or number, or a value set (see below). In Figure 1, the range of the *ingredients* attribute is Ingredient, and the range of the *id* attribute is a string.

* *ValueSets(c)*: a list of atomic values from which values of *a* can be drawn, where a value set is either an extensional list (fixed/static) or intensional (specified by ontology query). For example, a value set for a food element in an ingredient may be drawn from the food branch of the Food Ontology.

* *Inlined(a)* = {*True, False*}, indicating, when the range is a class, if the object should be nested/embedded, or passed by reference.

Additionally, a class *c* can include a set of identifier constraints:

$$IDSpaces (c_{i}) = \{prefix_{i}, \dots, prefix\}$$ (3)

4

SPIRES

![Overview of the SPIRES approach showing the flow from Schema and Text through OntoGPT to GPT-3+ and Public databases & ontologies, resulting in Structured Data.](page_5_image_1_v2.jpg)

Figure 3: Overview of the SPIRES approach. A knowledge schema and text containing instances defined in the schema are processed by OntoGPT, yielding a query for GPT-3 or newer, accessed through the OpenAI API. OntoGPT parses the result, grounding extracted instances with specific entries and terms retrieved from queries of databases and ontologies where possible. The final product is a set of structured data (instances and relationship) in the shapes defined by the schema. Icons by user Khoirin from the Noun Project (https://thenounproject.com/besticon/).

The constraint set is a list of strings that are the allowable prefixes that the identifier can take–for example, “WIKIDATA”, “MESH”, “GO”, or “FOODON”. The prefixes should come from a standard prefix registry such as BioRegistry [20] to ensure consistency across schemas and projects; SPIRES expects upper-case prefixes.

## 2.1 Evaluation of Entity Grounding

To determine the extent to which SPIRES improves entity grounding relative to prompting alone, we queried two GPT models with sets of ontology term labels with and without our grounding. We selected 100 terms at random from each of three ontologies: the Gene Ontology (GO), the Mouse Developmental Anatomy Ontology (EMAPA), and the MONDO Disease Ontology. The 16k GPT-3.5-turbo (gpt-3.5-turbo-16k) and the newly available GPT-4-turbo (gpt-4-1106-preview) models were each queried with the full term list in a single prompt each along with text requesting corresponding identifiers from the specified ontology (or, for SPIRES, a structured query based on a minimal schema). A match was considered successful for each pair of identifier and label in which the label text was parsed as a single entity, remained unchanged in the output, and matched to the correct identifier. The full evaluation and results are available in a code notebook online<sup>1</sup>.

## 2.2 Evaluation Against Chemical Disease Relation Task

We evaluated SPIRES on the Biocreative Chemical-Disease-Relation task [21]. We used all 500 abstracts of the BC5CDR test set and evaluated against the set of 1066 chemical-induces-disease (CID) triples. For each triple, the

<sup>1</sup>https://github.com/monarch-initiative/ontogpt-experiments/blob/main/experiments/ground_compare/Comparing_Grounding.ipynb

5

SPIRES

predicate is fixed, and the subject and object are always identifiers drawn from the Medical Subject Headings (MeSH) vocabulary [22]. Grounding was performed using multiple ontologies beyond MeSH, including three resources for chemical and drug information: Chemical Entities of Biological Interest (ChEBI) [23], DrugBank [24], and MedDRA [25] (See Table S1 for a full list of external resources used for grounding). We used the Translator NodeNormalizer [26] to normalize these to MeSH IDs to permit comparison with the test set. No fine tuning was performed. The training set was used to enhance our mappings of named entity spans to MeSH identifiers; after building this lexicon, the training set was discarded.

We provided SPIRES with a model of chemical to disease (CTD) associations based on the Biolink Model [27]. Biolink extends the simple triple model of associations to include qualifiers on the predicate, subject, and object. Subject and object qualifier information was discarded in this evaluation as extracting these details was not tested for in the original CDR benchmark. Statements with predicate qualifiers of "NOT" were discarded. We configured value sets for MeSH Disease and Chemical entries manually (see the full list of identifiers used to define these sets in Table S2). NER of chemical and disease entities was also evaluated based on ability to identify a corresponding MeSH. We compared two pre-processing approaches: a "chunking" approach in which input documents were processed as separate subsegments (essentially a sliding window approach) and a "no chunking" approach in which the entirety of the test corpus document title and abstract was passed in a prompt. Two OpenAI models were used in these comparisons: gpt-3.5-turbo and gpt-4.

# 3 Algorithm

The SPIRES extraction procedure takes as input (1) a schema $S$, (2) an entry point class $C$, and (3) a text $T$ (Figure 4, top). It returns a structured instance $i$ conforming to $S$, making use of a large language model (LLM) that allows prompt completion, such as GPT-3 and its more recent versions. The procedure is detailed below:

```mermaid
graph TD
    Schema[Schema] --> GenPrompt[Generate Prompt]
    Text[Text] --> GenPrompt
    GenPrompt --> CompPrompt[Complete Prompt]
    CompPrompt --> ParseComp[Parse Completion]
    ParseComp --> Ground[Ground]
    Ground --> Decision1{Additional<br/>non-terminals?}
    Decision1 -- Y --> GenPrompt
    Decision1 -- N --> Decision2{Create OWL?}
    Decision2 -- N --> Reason[Reason]
    Decision2 -- Y --> TransOWL[Translate to OWL]
    TransOWL --> Reason
    Reason --> End([ ])

    GenPrompt -.-> Prompt[Prompt]
    CompPrompt -.-> Payload[Completion<br/>Payload]
    ParseComp -.-> PartialInst[(partial)<br/>instance]
    Ground -.-> InstTerms[Instance +<br/>terms]
    TransOWL -.-> OWL[OWL]
```

Figure 4: Flowchart depicting the SPIRES algorithm.

6

SPIRES

*SPIRES(S, C, T):*

1. Generate the prompt: $p = GeneratePrompt(S, C, T)$
2. Perform prompt completion: $r = CompletePrompt(p)$
3. Parse results and recurse over nested structures:
$iu = ParseCompletion(r, S, C)$
4. Ground results using ontologies: $i = Ground(iu, S, C)$
5. (optional) translation to OWL: $ont = TranslateToOWL(i)$

## 3.1 Step 1: Generate Prompt

SPIRES first generates text for a prompt (Figure 4, Generate Prompt) to be provided to the LLM:

$$GeneratePrompt(S, C, T) = Instructions() + AttributeTemplate(S, C, T) + TextIntro() + T + Break() \quad (4)$$

Here, the *Instructions* function returns a piece of text such as "From the text below, extract the following entities in the following format".

The *AttributeTemplate* function generates a pseudo-YAML structure that is a template for results. For each $a$ in $Attributes(C)$, we write:

$$Name(a) + ":" + Prompt(a) + "\backslash n" \quad (5)$$

If *Prompt* is undefined for attribute $a$, then it is automatically generated from the name. If *Multivalued(a)* is True, then the text is preceded with "A semicolon-separated list".

The *TextIntro* function introduces a break between the template and the input text and is a fixed string "Text:". The *Break* function is also a fixed string that serves to demarcate the end of the text and is a sequence of three break characters, e.g. "===". As an example, when calling this function when $S=RecipeSchema$, $C=Ingredient$, and $T=$"garlic powder (2 tablespoons)", the following prompt would be generated:

```
Split the following piece of text into fields in the
following format:

food_item: <the food item>
amount: <the quantity of the ingredient>

Text:
garlic powder (2 tablespoons)

===
```

Note that typical input texts will be larger, except when the function is called recursively.

## 3.2 Step 2: Complete the Prompt

The generated prompt is provided to the LLM using a completion API (Figure 4, Complete Prompt). The nature of the prompt can be adapted for different language models; the OntoGPT implementation defaults to the orange GPT-3.5-turbo model [28] but is compatible with any model capable of delivering a payload orange that conforms to a prompt-specified structure. The intended completion results are a pseudo-YAML structure conforming to the specified template. For example, when passing the example prompt in Step 1, the return payload may be the following text:

```
food_item: garlic powder
amount: 2 tablespoons
```

## 3.3 Step 3: Completion Result Parsing and Recursive Extraction

The $ParseCompletion(r, S, C)$ function returns a pre-grounded instance object $i$ partially conforming to $C$. This step consists of two sub-steps: (1) parsing the pseudo-YAML; (2) recursively calling SPIRES on any inlined attributes.

7

SPIRES

For the parsing step (Figure 4, *Parse Completion*), the completion provided by the LLM is not guaranteed to be strict YAML or even conform directly to the specified template, so a heuristic approach is used. The response is separated by newlines into a list. Each line is split on the first instance of a “:”; the part before is matched against the attribute name, and the part after is the value, which is parsed as detailed below. Attribute matching is case-insensitive. All whitespace is normalized to underscores.

Each value $v$ is parsed according to the range and cardinality of the matched attribute $a$, populating each attribute $a$ of $i$:

$$i[a] = ParseValue(v) \hfill (6)$$

If $a$ is *multivalued*, then $v$ is first split according to a delimiter (default “;”), and the rules below are applied on each token; otherwise the rules below are applied directly.

Rule 1: If the range is a primitive data type (i.e. string, number, or boolean) then the value is returned as-is.

Rule 2: If the range of the attribute is a class, and the attribute is non-inlined (i.e. a reference) or an enumeration, then the value will be grounded, as specified in Step 4 below.

Rule 3: if the range of the attribute is an inlined class, then SPIRES is called recursively:

$$SPIRES(S, Range(a), v) \hfill (7)$$

This proceeds until a non-inlined class is reached. For example, given the example payload from the previous step, the attribute *food item* is a reference to an ontology class, so the value “garlic powder” is grounded using the grounding procedure (Step 4). The attribute *amount* is a reference to an inlined class *Quantity*, so this will be recursively parsed by calling `GeneratePrompt(RecipeSchema, Quantity, "2 tablespoons")`.

### 3.4 Step 4: Grounding and Normalization

All leaf nodes of the instance tree that correspond to named entities are grounded, i.e., mapped to an identifier in an existing vocabulary, ontology, or database (Figure 4, *Ground*). Classes representing named entities can each be annotated with one or more vocabularies. Each vocabulary is identified by a unique prefix. For example, in Figure 1, the FoodItem class could be annotated with both FOODON and Wikidata, indicating that grounding on labels can be performed using these vocabularies. Grounding on the string “garlic powder” may then yield FOODON:03301844 when the BioPortal [29] or AgroPortal annotator [30] is used, and WIKIDATA:Q10716334 when a Wikidata normalizer is used. The final results are normalized via validation against identifier constraints for the class. If $IDSpaces(c)$ is set, then the prefix of the identifier is checked against the list of valid prefixes. If $ValueSets(c)$ is set, then the value returned must be present in the value set.

### 3.5 Step 5: Translation to OWL and Reasoning

Step 4 produces an instance tree that can be directly represented in JSON or YAML syntax (both of which allow for arbitrary nesting of objects). For some KBs, this is sufficient. Further conversion to an ontological representation in OWL (Figure 4, *Translate to OWL*), and additional reasoning steps, then support checking for consistency and population of missing axioms. There are multiple methods for translating to OWL, including ROBOT templates [31], DOSDPs [32], and OTTR [33].

## 4 Implementation

We provide an implementation of SPIRES in Python as part of the OntoGPT Python package<sup>2</sup>, which provides both a command line interface (CLI) and a simple web application (Supplementary Figure S1). SPIRES uses LinkML [34] as its Knowledge Schema language. This allows for a full representation of the necessary schema elements while incorporating LinkML’s powerful mechanism for specifying static and dynamic value sets. For example, a value set can be constructed as a declarative query of the form “include branches A, B and C from ontology O<sub>1</sub>, excluding sub-branch D, and include all of ontology O<sub>2</sub>”. The LinkML framework also supports converting schemas to LinkML from forms such as SHACL [35], JSON-Schema [36], or SQL Data Definition Language, allowing their use with SPIRES.

SPIRES performs grounding and normalization with the Ontology Access Kit library (OAKlib) [37], which provides interfaces for multiple annotation tools (i.e., those providing links to external vocabularies and ontologies), including the Gilda entity normalization tool [18], the BioPortal annotator [38], and the Ontology Lookup Service [39]. For

<sup>2</sup>https://github.com/monarch-initiative/ontogpt

8

SPIRES

Table 1: Pre-made schemas. Example use cases are included but are not comprehensive. Note the CTD schema is deliberately restricted to only use the MESH vocabulary for purposes of evaluation. Identifiers refers to all ontologies, value sets, and other unique term sets incorporated in a given schema.


<table>
  <thead>
    <tr>
        <th>Schema</th>
        <th>Use Case</th>
        <th>Identifiers</th>
        <th>Text inputs</th>
    </tr>
  </thead>
  <tbody>
    <tr>
        <td>Food Recipes</td>
        <td>Enforcing consistent structure on stepwise processes</td>
        <td>FOODON, UO</td>
        <td>Unstructured and semi-structured recipes</td>
    </tr>
    <tr>
        <td>Drug mechanisms</td>
        <td>Integrating drug descriptions</td>
        <td>MONDO, CHEBI, MESH</td>
        <td>Mechanism of Action (MOA) descriptions</td>
    </tr>
    <tr>
        <td>Chemical-disease interactions</td>
        <td>Assembling knowledge graphs of chemical-impacted phenotypes</td>
        <td>MESH</td>
        <td>Abstracts describing effects of chemicals on conditions</td>
    </tr>
    <tr>
        <td>Metagenomic Samples</td>
        <td>Standardizing metadata for metagenomics</td>
        <td>ENVO</td>
        <td>Descriptions of environmental samples</td>
    </tr>
    <tr>
        <td>Mendelian Diseases</td>
        <td>Extracting disease relationships from literature</td>
        <td>MONDO, HPO</td>
        <td>Case studies or descriptions of Mendelian diseases</td>
    </tr>
  </tbody>
</table>

identifier normalization a number of services can be used, including OntoPortal mappings, with the default being the NCATS Biomedical Translator Node Normalizer [26].

The results of extraction can optionally be further processed using LinkML-OWL [40], which generates an OWL representation of instance data using mappings specified in a LinkML schema. This OWL file can be used as an input to ROBOT [31] to run OWL reasoning to check for logical inconsistencies and perform automated classification.

## 4.1 Standard Templates for Multiple Applications

The SPIRES implementation comes with a growing collection of ready-made schemas for multiple applications. These are primarily life-science focused, for example, deriving a pathway from a Mechanism of Action description in a database such as DrugBank. We also include a schema for food recipes to demonstrate general applicability in domains beyond the environmental and life sciences. Table 1 lists a selection of the pre-made schemas.

## 4.2 Extraction of Recipe Ontologies from Websites

To demonstrate the full functionality of OntoGPT we created a pipeline for extracting recipes from websites and generating an OWL ontology from the combined outputs. Recipes are extracted using the recipe-scrapers Python module<sup>3</sup>. The pipeline takes the output of scraping, concatenates the results into a text, then feeds this to OntoGPT using the recipe template. We use LinkML-OWL to map the recipe template to OWL axioms, such that each recipe is represented as a class defined by its ingredients and its steps. We use ROBOT to extract the relevant parts of the FOODON ontology, and merge this with the extraction results, combined with a manually coded simple recipe classification with defined classes for groupings such as “Meat Recipe” and “Wheat Based Recipe”. We use the Elk reasoner [41] to classify the results. The results of this process are highlighted in Figure S3.

## 4.3 Entity Grounding

Grounding entities with ontology terms is part of the core functionality of SPIRES and its value is well demonstrated in a direct comparison with the straightforward approach of directly querying an LLM with term descriptions. If we request the GO term for "integrase activity" we expect the response to include GO:0008907, for example. Of 100 GO terms chosen at random, SPIRES returned the correct identifiers for 98 when using GPT-3.5-turbo and 97 with GPT-4-turbo. Without SPIRES, GPT-3.5-turbo returned just 3 correct identifiers. Though it yielded 100 putative matches, few included correct GO identifiers. This "mass hallucination" may be an artifact of prompting with terms lacking surrounding context. Even so, it may be challenging to determine how much context is sufficient to improve grounding. GPT-4-turbo demonstrated a different challenge by consistently refusing to retrieve identifiers, returning responses such as "As an AI developed before 2023, I do not have real-time access to databases...". For the EMAPA mouse anatomy ontology, SPIRES returned correct identifiers for all 100 term descriptions, while GPT-3.5-turbo repeatedly provided identifiers from the EHDAA2 human anatomy ontology instead. GPT-4-turbo refused to ground EMAPA terms as it had with GO.

<sup>3</sup>https://github.com/hhursev/recipe-scrapers

9

SPIRES

Table 2: Extracted relation examples. All predicates are ’INDUCES’. Sources are PubMed identifiers (PMIDs). PMID 2160002 is “Vasodilation of large and small coronary vessels and hypotension induced by cromakalim and pinacidil” [42]. PMID 19154241 is a case report on lithium therapy [43]. PMID 10327032 is a study of hyperammonemic encephalopathy risks in cancer patients [44].


<table>
  <thead>
    <tr>
        <th>Source</th>
        <th>Subject</th>
        <th>Sub. qual.</th>
        <th>Predicate</th>
        <th>Object</th>
        <th>Object qual.</th>
    </tr>
  </thead>
  <tbody>
    <tr>
        <td>2160002</td>
        <td>MESH:D019806<br/>Cromakalim</td>
        <td>-</td>
        <td>INDUCES</td>
        <td>MESH:D014664<br/>Vasodilation</td>
        <td>large and small coronary vessels</td>
    </tr>
    <tr>
        <td>2160002</td>
        <td>MESH:D020110<br/>Pinacidil</td>
        <td>-</td>
        <td>INDUCES</td>
        <td>MESH:D014664<br/>Vasodilation</td>
        <td>large and small coronary vessels</td>
    </tr>
    <tr>
        <td>19154241</td>
        <td>MESH:D008094<br/>Lithium</td>
        <td>Chronic</td>
        <td>INDUCES</td>
        <td>MESH:D006934<br/>Hypercalcemia</td>
        <td>-</td>
    </tr>
    <tr>
        <td>10327032</td>
        <td>MESH:D005472<br/>Fluorouracil</td>
        <td>-</td>
        <td>INDUCES</td>
        <td>MESH:D001927<br/>Brain Diseases</td>
        <td>Transient</td>
    </tr>
  </tbody>
</table>

MONDO terms posed some surprising difficulty: SPIRES with GPT-3.5-turbo correctly returned 97 of 100 identifiers but SPIRES with GPT-4-turbo returned just 18 correct matches. In some cases, this may have been due to incorrectly parsing entities (e.g., parsing "UV-induced skin damage, susceptibility to" as "skin damage"). As with GO, prompting without SPIRES only returned one correct identifier at most from both GPT-3.5-turbo and GPT-4-turbo.

## 4.4 Evaluation on BioCreative Chemical Disease Relation Task

We evaluated SPIRES on the BioCreative Chemical-Disease-Relation (BC5CDR) task corpus. To demonstrate the zero-shot learning approach, we did not perform any fine tuning using the training set. The training set was used to enhance our mappings of named entity spans to MeSH identifiers and was then discarded. For our CTD schema (see Figure S2), we follow the Biolink Model [27] which extends the simple triple model of associations to include qualifiers on the predicate, subject, and object. This yields finer-grained predictions; for example, SPIRES correctly parses the statements in Table 2. In these cases, SPIRES grounds the drug entity Cromakalim to its corresponding MeSH identifier and extracts its relationship with vasodilation along with a qualifier noting the observation is specific to "large and small coronary vessels", an anatomical entity worthy of further grounding (though this was not explored within the original BC5CDR task). Similarly, the correctly extracted relationship between lithium and hypercalcemia includes the qualifier that the observation pertains to chronic lithium exposure.

When evaluating, we discard subject and object qualifier information, as this is not tested for in the original CDR benchmark. If the predicate qualifier is “NOT” then we discard the whole statement. Note that in the examples in Table 2, even though we evaluated the first two statements to be a correct interpretation of the abstract, they were counted as false negatives; the corresponding triple was not in the test set, presumably an error of omission.

For SPIRES, we saw initially encouraging results on the BC5CDR task with chunking and GPT-3.5-turbo: we observed an F-score of 41.16, precision of 0.43, and recall of 0.39. Using the "no chunking" approach (i.e., no preprocessing of the test document) yielded an F-score of 36.64 (precision 0.63, recall 0.26) with GPT-3.5-turbo and an F-score of 43.80 (precision 0.69, recall 0.32). For NER results alone (i.e., correct grounding against MeSH for chemical and disease entities), see Table S3.

These results place SPIRES just below the average of all 18 teams that participated in the original CDR challenge. We assume all 18 teams used the full training set, whereas with SPIRES there was no task-specific training or fine tuning. For comparison, Luo et al. report an F-score of 44.98 on BC5CDR with their biomedical domain-specific, trained-from-scratch BioGPT model [9]. We note that the best-scoring relation extraction results from the CDR task achieved an impressive score of 0.57, though with a model trained on a large and carefully engineered set of training examples [45]. SPIRES bypasses this step but may see further improvement with fine-tuned and/or domain-specific LLMs.

# 5 Discussion

## 5.1 Comparable Methods

SPIRES is a well-developed and generally model-agnostic approach for information extraction designed with structured schemas and standardized ontologies in mind. Some recent efforts have made great strides in leveraging the first type of resource, i.e., they address the task of aligning extracted information with pre-defined data models. The fine-tuned

10

SPIRES

GPT-3-based approach described by Dunn and Dagdelen et al. employs engineered schemas to extract structured relationships from unstructured text in materials chemistry [46]. The authors of the LLMs4OL approach also explored application of LLMs to information extraction, but concluded that the models are not yet sufficiently flexible for ontology-driven needs [47]. We also consider the task of ontology alignment to be related to our efforts; we have found that LLMs can noticeably improve accuracy in ontology alignment [48] and the development of general frameworks such as Agent-OM [49] may further improve the grounding inherent to information extraction.

## 5.2 Choosing a Model

OntoGPT currently supports both select open LLMs and the OpenAI API. Running OntoGPT across a large corpus with OpenAI models may be prohibitively expensive for some users. Additionally, the use of this API involves closed models with inscrutable training data, which may be plagued by biases [50]. Though our experiments here generally concern GPT-3 and 4, the rapid pace of model development will ensure access to progressively more capable (and ideally, more transparent) language models. Smaller LMs such as LLaMA have been shown to outperform models ten times their size [51], and it is possible to fine-tune these into instruction following models [52]. LLMs based on LLaMA2 and adapted for biomedical language, including BioMedGPT-LM [53] and Radiology-Llama2 [54], may complement the grounding provided through SPIRES.

## 5.3 Reliability and Hallucinations

A common problem with LLMs is hallucination of results (producing factually invalid statements that are not consistent with the input text) [5, 50]. We crafted prompts to limit hallucination, asking only for the LM to extract what was found in the text, and keeping default low-creativity settings. On examination we found that hallucinations were generally infrequent, with most false positives and negatives attributable to incorrect relation extraction. It is worth noting that LLM interfaces designed for direct function calling may duplicate some of the data structure enforcement afforded by SPIRES but do not alleviate the issue of hallucination: a model may still improperly associate real or fictional ontology identifiers with extracted entities when queried without aid of our approach.

Some text generation may yield technically correct results. For example, one result extracted from the title "Increased frequency and severity of angio-oedema related to long-term therapy with angiotensin-converting enzyme inhibitor in two patients", yielded "Lisinopril INDUCES angio-oedema". Lisinopril is in fact a subtype of ACE inhibitor, and the extracted association is supported by other literature. However, this more precise statement is not the one that is in the original text. Presumably the LM is substituting the class of drug with a specific member here, but it is unclear why it does it on this occasion. Until there are better methods to control this hallucination and explain justifications for statements in terms of the text and prior knowledge, results from LMs should be carefully validated before being entered into KBs.

SPIRES is a new approach to information extraction that leverages recent advances in large language models to populate complex knowledge schemas from unstructured text. It uses zero-shot learning to identify and extract relevant information from query text, which is then normalized and grounded using existing ontologies and vocabularies. SPIRES requires no model tuning or training data. The approach is customizable, flexible, and can be used to populate knowledge schemas across varied domains. We envision SPIRES being used not in isolation, but rather in synergistic strategies combining human expertise, linguistic pattern recognition, deep learning and classical deductive reasoning approaches. SPIRES is one component of a growing toolkit of methods for transforming noisy, heterogeneous information into actionable knowledge.

# 6 Competing interests

No competing interest is declared.

# 7 Acknowledgements

## 7.1 Funding

This work was supported by the National Institutes of Health National Human Genome Research Institute [RM1 HG010860]; National Institutes of Health Office of the Director [R24 OD011883]; and the Director, Office of Science, Office of Basic Energy Sciences, of the US Department of Energy [DE-AC0205CH11231 to J.H.C., H.H., N.L.H., M.J., S.M., J.T.R, and C.J.M.]. We also gratefully acknowledge Bosch Research for their support of this research project.

11

SPIRES

# References

[1] Denny Vrandečić. Wikidata: A new platform for collaborative data collection. In *Proceedings of the 21st International Conference on World Wide Web, WWW '12 Companion*, pages 1063–1064, New York, NY, USA, 2012. ACM. ISBN 9781450312301. doi:10.1145/2187980.2188242.

[2] The Gene Ontology Consortium. The gene ontology resource: 20 years and still GOing strong. *Nucleic Acids Res.*, 47(D1):D330–D338, January 2019. ISSN 0305-1048, 1362-4962. doi:10.1093/nar/gky1055.

[3] Antonio Fabregat, Steven Jupe, Lisa Matthews, Konstantinos Sidiropoulos, Marc Gillespie, Phani Garapati, Robin Haw, Bijay Jassal, Florian Korninger, Bruce May, Marija Milacic, Corina Duenas Roca, Karen Rothfels, Cristoffer Sevilla, Veronica Shamovsky, Solomon Shorser, Thawfeek Varusai, Guilherme Viteri, Joel Weiser, Guanming Wu, Lincoln Stein, Henning Hermjakob, and Peter D’Eustachio. The reactome pathway knowledgebase. *Nucleic Acids Res.*, 46(D1):D649–D655, January 2018. ISSN 0305-1048, 1362-4962. doi:10.1093/nar/gkx1132.

[4] Samy Ateia and Udo Kruschwitz. Is ChatGPT a biomedical expert? – exploring the Zero-Shot performance of current GPT models in biomedical tasks. In *CLEF 2023: Conference and Labs of the Evaluation Forum*, June 2023. doi:10.48550/arXiv.2306.16108.

[5] Ziwei Ji, Nayeon Lee, Rita Frieske, Tiezheng Yu, Dan Su, Yan Xu, Etsuko Ishii, Yejin Bang, Wenliang Dai, Andrea Madotto, and Pascale Fung. Survey of hallucination in natural language generation. *arXiv*, February 2022. doi:10.1145/3571730.

[6] Allyson Ettinger. What BERT is not: Lessons from a new suite of psycholinguistic diagnostics for language models. *Trans. Assoc. Comput. Linguist.*, 8:34–48, December 2020. ISSN 2307-387X. doi:10.1162/tacl_a_00298.

[7] Yanshan Wang, Sunyang Fu, Feichen Shen, Sam Henry, Ozlem Uzuner, and Hongfang Liu. The 2019 n2c2/OHNLP track on clinical semantic textual similarity: Overview. *JMIR Med Inform*, 8(11):e23375, November 2020. ISSN 2291-9694. doi:10.2196/23375.

[8] Mihir P Khambete, William Su, Juan C Garcia, and Marcus A Badgeley. Quantification of BERT diagnosis generalizability across medical specialties using semantic dataset distance. *AMIA Jt Summits Transl Sci Proc*, 2021:345–354, May 2021. ISSN 2153-4063. doi:10.1371/journal.pone.0112774.

[9] Renqian Luo, Liai Sun, Yingce Xia, Tao Qin, Sheng Zhang, Hoifung Poon, and Tie-Yan Liu. BioGPT: generative pre-trained transformer for biomedical text generation and mining. *Brief. Bioinform.*, 23(6), November 2022. ISSN 1467-5463, 1477-4054. doi:10.1093/bib/bbac409.

[10] Robert M Wachter and Erik Brynjolfsson. Will generative artificial intelligence deliver on its promise in health care? *JAMA*, November 2023. ISSN 0098-7484, 1538-3598. doi:10.1001/jama.2023.25054.

[11] Ashish Vaswani, Noam Shazeer, Niki Parmar, Jakob Uszkoreit, Llion Jones, Aidan N Gomez, Łukasz Kaiser, Illia Polosukhin, Lukasz Kaiser, and Illia Polosukhin. Attention is all you need. In *31st Conference on Neural Information Processing Systems (NIPS 2017)*, Long Beach, CA, USA, June 2017. doi:10.48550/arXiv.1706.03762.

[12] Tom B Brown, Benjamin Mann, Nick Ryder, Melanie Subbiah, Jared Kaplan, Prafulla Dhariwal, Arvind Neelakantan, Pranav Shyam, Girish Sastry, Amanda Askell, Sandhini Agarwal, Ariel Herbert-Voss, Gretchen Krueger, Tom Henighan, Rewon Child, Aditya Ramesh, Daniel M Ziegler, Jeffrey Wu, Clemens Winter, Christopher Hesse, Mark Chen, Eric Sigler, Mateusz Litwin, Scott Gray, Benjamin Chess, Jack Clark, Christopher Berner, Sam McCandlish, Alec Radford, Ilya Sutskever, and Dario Amodei. Language models are Few-Shot learners. *arXiv*, May 2020. doi:10.48550/arXiv.2005.14165.

[13] Oren Ben-Kiki, Clark Evans, and Ingy Döt Net. YAML ain’t markup language (YAML™) version 1.2.2. https://yaml.org/spec/1.2.2/, 2021. Accessed: 2023-3-28.

[14] Damion M Dooley, Emma J Griffiths, Gurinder S Gosal, Pier L Buttigieg, Robert Hoehndorf, Matthew C Lange, Lynn M Schriml, Fiona S L Brinkman, and William W L Hsiao. FoodOn: a harmonized food ontology to increase global food traceability, quality control and data integration. *NPJ Sci Food*, 2:23, December 2018. ISSN 2396-8370. doi:10.1038/s41538-018-0032-6.

[15] G Schadow, C J McDonald, J G Suico, U Föhring, and T Tolxdorff. Units of measure in clinical information systems. *J. Am. Med. Inform. Assoc.*, 6(2):151–162, 1999. ISSN 1067-5027. doi:10.1136/jamia.1999.0060151.

[16] Christian Bizer, Jens Lehmann, Georgi Kobilarov, Sören Auer, Christian Becker, Richard Cyganiak, and Sebastian Hellmann. DBpedia - a crystallization point for the web of data. *Journal of Web Semantics*, 7(3):154–165, September 2009. ISSN 1570-8268. doi:10.1016/j.websem.2009.07.002.

[17] John Graybeal, Clement Jonquet, Nicola Fiore, and Mark A Musen. Adoption of BioPortal’s ontology registry software: The emerging OntoPortal community. In *RDA P13 2019 - 13th Research Data Alliance Plenary Meeting*, April 2019.

12

SPIRES

[18] Benjamin M Gyori, Charles Tapley Hoyt, and Albert Steppi. Gilda: biomedical entity text normalization with machine-learned disambiguation as a service. *Bioinformatics Advances*, 2(1), January 2022. doi:10.1093/bioadv/vbac034.

[19] Lenz Furrer, Anna Jancso, Nicola Colic, and Fabio Rinaldi. OGER : hybrid multi-type entity recognition. *Journal of Cheminformatics*, 11(1), 2019. doi:10.1186/s13321-018-0326-3.

[20] Charles Tapley Hoyt, Meghan Balk, Tiffany J Callahan, Daniel Domingo-Fernández, Melissa A Haendel, Harshad B Hegde, Daniel S Himmelstein, Klas Karis, John Kunze, Tiago Lubiana, Nicolas Matentzoglu, Julie McMurry, Sierra Moxon, Christopher J Mungall, Adriano Rutz, Deepak R Unni, Egon Willighagen, Donald Winston, and Benjamin M Gyori. Unifying the identification of biomedical entities with the bioregistry. *Sci Data*, 9(1):714, November 2022. ISSN 2052-4463. doi:10.1038/s41597-022-01807-3.

[21] Jiao Li, Yueping Sun, Robin J Johnson, Daniela Sciaky, Chih-Hsuan Wei, Robert Leaman, Allan Peter Davis, Carolyn J Mattingly, Thomas C Wiegers, and Zhiyong Lu. BioCreative V CDR task corpus: a resource for chemical disease relation extraction. *Database*, 2016:baw068, May 2016. ISSN 0162-4105, 1758-0463. doi:10.1093/database/baw068.

[22] C E Lipscomb. Medical subject headings (MeSH). *Bull. Med. Libr. Assoc.*, 88(3):265–266, July 2000. ISSN 0025-7338.

[23] Janna Hastings, Gareth Owen, Adriano Dekker, Marcus Ennis, Namrata Kale, Venkatesh Muthukrishnan, Steve Turner, Neil Swainston, Pedro Mendes, and Christoph Steinbeck. ChEBI in 2016: Improved services and an expanding collection of metabolites. *Nucleic Acids Res.*, 44(D1):D1214–9, January 2016. ISSN 0305-1048, 1362-4962. doi:10.1093/nar/gkv1031.

[24] David S Wishart, Yannick D Feunang, An C Guo, Elvis J Lo, Ana Marcu, Jason R Grant, Tanvir Sajed, Daniel Johnson, Carin Li, Zinat Sayeeda, Nazanin Assempour, Ithayavani Iynkkaran, Yifeng Liu, Adam Maciejewski, Nicola Gale, Alex Wilson, Lucy Chin, Ryan Cummings, Diana Le, Allison Pon, Craig Knox, and Michael Wilson. DrugBank 5.0: a major update to the DrugBank database for 2018. *Nucleic Acids Res.*, 46(D1):D1074–D1082, January 2018. ISSN 0305-1048. doi:10.1093/nar/gkx1037.

[25] Elliot G Brown, Louise Wood, and Sue Wood. The medical dictionary for regulatory activities (MedDRA). *Drug Saf.*, 20(2):109–117, 1999. ISSN 0114-5916. doi:10.2165/00002018-199920020-00002.

[26] Karamarie Fecho, Anne T Thessen, Sergio E Baranzini, Chris Bizon, Jennifer J Hadlock, Sui Huang, Ryan T Roper, Noel Southall, Casey Ta, Paul B Watkins, Mark Williams, Hao Xu, William Byrd, Vlado Dančík, Marc P Duby, Michel Dumontier, Gustavo Glusman, Nomi L Harris, Eugene W Hinderer, Greg Hyde, Adam Johs, Andrew Su, Guangrong Qin, Qian Zhu, and Biomedical Data Translator Consortium. Progress toward a universal biomedical data translator. *Clin. Transl. Sci.*, May 2022. ISSN 1752-8054, 1752-8062. doi:10.1111/cts.13301.

[27] Deepak R Unni, Sierra A T Moxon, Michael Bada, Matthew Brush, Richard Bruskiewich, J Harry Caufield, Paul A Clemons, Vlado Dancik, Michel Dumontier, Karamarie Fecho, Gustavo Glusman, Jennifer J Hadlock, Nomi L Harris, Arpita Joshi, Tim Putman, Guangrong Qin, Stephen A Ramsey, Kent A Shefchek, Harold Solbrig, Karthik Soman, Anne E Thessen, Melissa A Haendel, Chris Bizon, Christopher J Mungall, Liliana Acevedo, Stanley C Ahalt, John Alden, Ahmed Alkanaq, Nada Amin, Ricardo Avila, Jim Balhoff, Sergio E Baranzini, Andrew Baumgartner, William Baumgartner, Basazin Belhu, Mackenzie Brandes, Namdi Brandon, Noel Burtt, William Byrd, Jackson Callaghan, Marco Alvarado Cano, Steven Carrell, Remzi Celebi, James Champion, Zhehuan Chen, Mei-Jan Chen, Lawrence Chung, Kevin Cohen, Tom Conlin, Dan Corkill, Maria Costanzo, Steven Cox, Andrew Crouse, Camerron Crowder, Mary E Crumbley, Cheng Dai, Vlado Dančík, Ricardo De Miranda Azevedo, Eric Deutsch, Jennifer Dougherty, Marc P Duby, Venkata Duvvuri, Stephen Edwards, Vincent Emonet, Nathaniel Fehrmann, Jason Flannick, Aleksandra M Foksinska, Vicki Gardner, Edgar Gatica, Amy Glen, Prateek Goel, Joseph Gormley, Alon Greyber, Perry Haaland, Kristina Hanspers, Kaiwen He, Kaiwen He, Jeff Henrickson, Eugene W Hinderer, Maureen Hoatlin, Andrew Hoffman, Sui Huang, Conrad Huang, Robert Hubal, Kenneth Huellas-Bruskiewicz, Forest B Huls, Lawrence Hunter, Greg Hyde, Tursynay Issabekova, Matthew Jarrell, Lindsay Jenkins, Adam Johs, Jimin Kang, Richa Kanwar, Yaphet Kebede, Keum Joo Kim, Alexandria Kluge, Michael Knowles, Ryan Koesterer, Daniel Korn, David Koslicki, Ashok Krishnamurthy, Lindsey Kvarfordt, Jay Lee, Margaret Leigh, Jason Lin, Zheng Liu, Shaopeng Liu, Chunyu Ma, Andrew Magis, Tarun Mamidi, Meisha Mandal, Michelle Mantilla, Jeffrey Massung, Denise Mauldin, Jason McClelland, Julie McMurry, Philip Mease, Luis Mendoza, Marian Mersmann, Abrar Mesbah, Matthew Might, Kenny Morton, Sandrine Muller, Arun Teja Muluka, John Osborne, Phil Owen, Michael Patton, David B Peden, R Carter Peene, Bria Persaud, Emily Pfaff, Alexander Pico, Elizabeth Pollard, Guthrie Price, Shruti Raj, Jason Reilly, Anders Riutta, Jared Roach, Ryan T Roper, Greg Rosenblatt, Irit Rubin, Sienna Rucka, Nathaniel Rudavsky-Brody, Rayn Sakaguchi, Eugene Santos, Kevin Schaper, Charles P Schmitt, Shepherd Schurman, Erik Scott, Sarah Seitanakis, Priya Sharma, Ilya Shmulevich, Manil Shrestha, Shalki Shrivastava, Meghamala Sinha, Brett Smith, Noel Southall, Nicholas Southern, Lisa

13

SPIRES

Stillwell, Michael “Michi” Strasser, Andrew I Su, Casey Ta, Anne E Thessen, Jillian Tinglin, Lucas Tonstad, Thi Tran-Nguyen, Alexander Tropsha, Gaurav Vaidya, Luke Veenhuis, Adam Viola, Marcin Grotthuss, Max Wang, Patrick Wang, Paul B Watkins, Rosina Weber, Qi Wei, Chunhua Weng, Jordan Whitlock, Mark D Williams, Andrew Williams, Finn Womack, Erica Wood, Chunlei Wu, Jiwen Kevin Xin, Hao Xu, Colleen Xu, Chase Yakaboski, Yao Yao, Hong Yi, Arif Yilmaz, Marissa Zheng, Xinghua Zhou, Eric Zhou, Qian Zhu, Tom Zisk, and The Biomedical Data Translator Consortium. Biolink model: A universal schema for knowledge graphs in clinical, biomedical, and translational science. *Clin. Transl. Sci.*, June 2022. ISSN 1752-8054, 1752-8062. doi:10.1111/cts.13302.

[28] OpenAI. OpenAI API. https://platform.openai.com/docs/models, 2023. Accessed: 2023-3-27.

[29] P L Whetzel, N F Noy, N H Shah, P R Alexander, C Nyulas, T Tudorache, and M A Musen. BioPortal: enhanced functionality via new web services from the national center for biomedical ontology to access and use ontologies in software applications. *Nucleic Acids Res.*, 39(suppl):W541–W545, July 2011. ISSN 0305-1048. doi:10.1093/nar/gkr469.

[30] Clément Jonquet, Anne Toulet, Elizabeth Arnaud, Sophie Aubin, Esther Dzalé Yeumo, Vincent Emonet, John Graybeal, Marie-Angélique Laporte, Mark A Musen, Valeria Pesce, and Pierre Larmande. AgroPortal: A vocabulary and ontology repository for agronomy. *Comput. Electron. Agric.*, 144:126–143, January 2018. ISSN 0168-1699. doi:10.1016/j.compag.2017.10.012.

[31] Rebecca C Jackson, James P Balhoff, Eric Douglass, Nomi L Harris, Christopher J Mungall, and James A Overton. ROBOT: A tool for automating ontology workflows. *BMC Bioinformatics*, 20(1):407, July 2019. ISSN 1471-2105. doi:10.1186/s12859-019-3002-3.

[32] David Osumi-Sutherland, Melanie Courtot, James P Balhoff, and Christopher Mungall. Dead simple OWL design patterns. *J. Biomed. Semantics*, 8(1):18, 2017. ISSN 2041-1480. doi:10.1186/s13326-017-0126-0.

[33] Christian Kindermann, Daniel P Lupp, Uli Sattler, and Evgenij Thorstensen. Generating ontologies from templates: A Rule-Based approach for capturing regularity. *arXiv*, page 13, 2018. doi:10.48550/arXiv.1809.10436.

[34] Sierra Moxon, Harold Solbrig, Deepak Unni, Dazhi Jiao, Richard Bruskiewich, James Balhoff, Gaurav Vaidya, William Duncan, Harshad Hegde, Mark Miller, and Others. The linked data modeling language (LinkML): A General-Purpose data modeling framework grounded in Machine-Readable semantics. In *CEUR Workshop Proceedings*, volume 3073, pages 148–151, 2021.

[35] Paolo Pareti and George Konstantinidis. A review of SHACL: From data validation to schema reasoning for RDF graphs. In *Reasoning Web. Declarative Artificial Intelligence*, pages 115–144. Springer International Publishing, 2022. doi:10.1007/978-3-030-95481-9_6.

[36] JSON schema. http://json-schema.org/, 2022. Accessed: 2023-3-28.

[37] Chris Mungall, Harshad, Patrick Kalita, Charles Tapley Hoyt, Sujay Patil, Marcin p Joachimiak, Joe Flack, David Linke, Deepak, Sierra Moxon, Nico Matentzoglu, Vinícius de Souza, Glass, Harry Caufield, Jules Jacobsen, Justin Reese, Nomi Harris, and Shawn Tan. INCATools/ontology-access-kit: v0.2.1. https://github.com/INCATools/ontology-access-kit, March 2023.

[38] Clement Jonquet, Nigam H Shah, and Mark A Musen. The open biomedical annotator. *Summit Transl Bioinform*, 2009:56–60, March 2009. ISSN 2153-6430.

[39] Simon Jupp, Tony Burdett, James Malone, Catherine Leroy, Matt Pearce, Julie Mcmurry, and Helen Parkinson. A new ontology lookup service at EMBL-EBI. http://ceur-ws.org/Vol-1546/paper_29.pdf, 2015. Accessed: 2023-1-3.

[40] Chris Mungall, Sujay Patil, and Nomi Harris. linkml/linkml-owl: v0.2.4. https://zenodo.org/record/7384531, December 2022.

[41] Yevgeny Kazakov and Pavel Klinov. Advancing ELK: Not only performance matters. In Diego Calvanese and Boris Konev, editors, *Proceedings of the 28th International Workshop on Description Logics (DL-15)*. CEUR Workshop Proceedings 2015., 2015.

[42] J F Giudicelli, C D la Rochelle, and A Berdeaux. Effects of cromakalim and pinacidil on large epicardial and small coronary arteries in conscious dogs. *J. Pharmacol. Exp. Ther.*, 255(2):836–842, November 1990. ISSN 0022-3565.

[43] Mian M Rizwan and Nancy D Perrier. Long-term lithium therapy leading to hyperparathyroidism: a case report. *Perspect. Psychiatr. Care*, 45(1):62–65, January 2009. ISSN 0031-5990, 1744-6163. doi:10.1111/j.1744-6163.2009.00201.x.

14

SPIRES

[44] C C Liaw, H M Wang, C H Wang, T S Yang, J S Chen, H K Chang, Y C Lin, S J Liaw, and C T Yeh. Risk of transient hyperammonemic encephalopathy in cancer patients who received continuous infusion of 5-fluorouracil with the complication of dehydration and infection. *Anticancer Drugs*, 10(3):275–281, March 1999. ISSN 0959-4973. doi:10.1097/00001813-199903000-00004.

[45] Jun Xu, Yonghui Wu, Yaoyun Zhang, Jingqi Wang, Ruiling Liu, Qiang Wei, and Hua Xu. UTH-CCB@BioCreative V CDR task: Identifying chemical-induced disease relations in biomedical text. In *Proceedings of the Fifth BioCreative Challenge Evaluation Workshop*, pages 254–259, July 2015.

[46] Alexander Dunn, John Dagdelen, Nicholas Walker, Sanghoon Lee, Andrew S Rosen, Gerbrand Ceder, Kristin Persson, and Anubhav Jain. Structured information extraction from complex scientific text with fine-tuned large language models. *arXiv*, December 2022. doi:10.48550/arXiv.2212.05238.

[47] Hamed Babaei Giglou, Jennifer D’Souza, and Sören Auer. LLMs4OL: Large language models for ontology learning. In *The Semantic Web – ISWC 2023*, pages 408–427. Springer Nature Switzerland, 2023. doi:10.1007/978-3-031-47240-4_22.

[48] Nicolas Matentzoglu, J Harry Caufield, Harshad B Hegde, Justin T Reese, Sierra Moxon, Hyeongsik Kim, Nomi L Harris, Melissa A Haendel, and Christopher J Mungall. MapperGPT: Large language models for linking and mapping entities. *arXiv*, October 2023. doi:10.48550/arXiv.2310.03666.

[49] Zhangcheng Qiang, Weiqing Wang, and Kerry Taylor. Agent-OM: Leveraging large language models for ontology matching. *arXiv*, December 2023. doi:10.48550/arXiv.2312.00326.

[50] Emily M. Bender, Timnit Gebru, Angelina McMillan-Major, and Shmargaret Shmitchell. On the dangers of stochastic parrots: Can language models be too big? In *Proceedings of the 2021 ACM Conference on Fairness, Accountability, and Transparency*, FAccT ’21, page 610–623, New York, NY, USA, 2021. Association for Computing Machinery. ISBN 9781450383097. doi:10.1145/3442188.3445922. URL https://doi.org/10.1145/3442188.3445922.

[51] Hugo Touvron, Thibaut Lavril, Gautier Izacard, Xavier Martinet, Marie-Anne Lachaux, Timothée Lacroix, Baptiste Rozière, Naman Goyal, Eric Hambro, Faisal Azhar, Aurelien Rodriguez, Armand Joulin, Edouard Grave, and Guillaume Lample. Llama: Open and efficient foundation language models. *arXiv*, 2023. doi:10.48550/arXiv.2302.13971.

[52] Renrui Zhang, Jiaming Han, Aojun Zhou, Xiangfei Hu, Shilin Yan, Pan Lu, Hongsheng Li, Peng Gao, and Yu Qiao. Llama-adapter: Efficient fine-tuning of language models with zero-init attention. *arXiv*, 2023. doi:10.48550/arXiv.2303.16199.

[53] Yizhen Luo, Jiahuan Zhang, Siqi Fan, Kai Yang, Yushuai Wu, Mu Qiao, and Zaiqing Nie. BioMedGPT: Open multimodal generative pre-trained transformer for BioMedicine. *arXiv*, August 2023. doi:10.48550/arXiv.2308.09442.

[54] Zhengliang Liu, Yiwei Li, Peng Shu, Aoxiao Zhong, Longtao Yang, Chao Ju, Zihao Wu, Chong Ma, Jie Luo, Cheng Chen, Sekeun Kim, Jiang Hu, Haixing Dai, Lin Zhao, Dajiang Zhu, Jun Liu, Wei Liu, Dinggang Shen, Tianming Liu, Quanzheng Li, and Xiang Li. Radiology-Llama2: Best-in-Class large language model for radiology. *arXiv*, August 2023. doi:10.48550/arXiv.2309.06419.

[55] Mark A Musen and Protégé Team. The protégé project: A look back and a look forward. *AI Matters*, 1(4):4–12, June 2015. ISSN 2372-3483. doi:10.1145/2757001.2757003.

[56] Nicholas Sioutos, Sherri de Coronado, Margaret W Haber, Frank W Hartel, Wen-Ling Shaiu, and Lawrence W Wright. NCI thesaurus: a semantic model integrating cancer-related clinical and molecular information. *J. Biomed. Inform.*, 40(1):30–43, February 2007. ISSN 1532-0464, 1532-0480. doi:10.1016/j.jbi.2006.02.013.

[57] Christopher J Mungall, Julie A McMurry, Sebastian Köhler, James P Balhoff, Charles Borromeo, Matthew Brush, Seth Carbon, Tom Conlin, Nathan Dunn, Mark Engelstad, Erin Foster, J P Gourdine, Julius O B Jacobsen, Dan Keith, Bryan Laraway, Suzanna E Lewis, Jeremy NguyenXuan, Kent Shefchek, Nicole Vasilevsky, Zhou Yuan, Nicole Washington, Harry Hochheiser, Tudor Groza, Damian Smedley, Peter N Robinson, and Melissa A Haendel. The monarch initiative: an integrative data and analytic platform connecting phenotypes to genotypes across species. *Nucleic Acids Res.*, 45(D1):D712–D722, January 2017. ISSN 0305-1048, 1362-4962. doi:10.1093/nar/gkw1128.

[58] Sebastian Köhler, Michael Gargano, Nicolas Matentzoglu, Leigh C Carmody, David Lewis-Smith, Nicole A Vasilevsky, Daniel Danis, Ganna Balagura, Gareth Baynam, Amy M Brower, Tiffany J Callahan, Christopher G Chute, Johanna L Est, Peter D Galer, Shiva Ganesan, Matthias Griese, Matthias Haimel, Julia Pazmandi, Marc Hanauer, Nomi L Harris, Michael J Hartnett, Maximilian Hastreiter, Fabian Hauck, Yongqun He, Tim Jeske, Hugh Kearney, Gerhard Kindle, Christoph Klein, Katrin Knoflach, Roland Krause, David Lagorce, Julie A McMurry, Jillian A Miller, Monica C Munoz-Torres, Rebecca L Peters, Christina K Rapp, Ana M Rath, Shahmir A

15

SPIRES

Rind, Avi Z Rosenberg, Michael M Segal, Markus G Seidel, Damian Smedley, Tomer Talmy, Yarlalu Thomas, Samuel A Wiafe, Julie Xian, Zafer Yüksel, Ingo Helbig, Christopher J Mungall, Melissa A Haendel, and Peter N Robinson. The human phenotype ontology in 2021. *Nucleic Acids Res.*, 49(D1):D1207–D1217, January 2021. ISSN 0305-1048, 1362-4962. doi:10.1093/nar/gkaa1043.

[59] Lynn M Schriml, Elvira Mitraka, James Munro, Becky Tauber, Mike Schor, Lance Nickle, Victor Felix, Linda Jeng, Cynthia Bearer, Richard Lichenstein, Katharine Bisordi, Nicole Campion, Brooke Hyman, David Kurland, Connor Patrick Oates, Siobhan Kibbey, Poorna Sreekumar, Chris Le, Michelle Giglio, and Carol Greene. Human disease ontology 2018 update: classification, content and workflow expansion. *Nucleic Acids Res.*, 47(D1): D955–D962, January 2019. ISSN 0305-1048, 1362-4962. doi:10.1093/nar/gky1032.

16

SPIRES

# 8 Supplementary Data

![Screenshot of web-ontogpt interface showing a form entry page (a) and structured results (b).](page_17_image_1_v2.jpg)

## a
**Select Schema**: gocam.GoCamAnnotations [dropdown]

**Title**: β-Catenin Is Required for the cGAs/STING Signaling Pathway but Antagonized by the Herpes Simplex Virus 1 US3 Protein

**Text**:
The cGAS/STING-mediated DNA-sensing signaling pathway is crucial for interferon (IFN) production and host antiviral responses. Herpes simplex virus I (HSV-1) is a DNA virus that has evolved multiple strategies to evade host immune responses. Here, we demonstrate that the highly conserved β-catenin protein in the Wnt signaling pathway is an important factor to enhance the transcription of type I interferon (IFN-I) in the cGAS/STING signaling pathway, and the production of IFN-I mediated by β-catenin was antagonized by HSV-1 US3 protein via its kinase activity. Infection by US3-deficienct HSV-1 and its kinase-dead variants failed to downregulate IFN-I and IFN-stimulated gene (ISG) production induced by β-catenin. Consistent with this, absence of β-catenin enhanced the replication of US3-deficienct HSV-1, but not wild-type HSV-1. The underlying mechanism was the interaction of US3 with β-catenin and its hyperphosphorylation of β-catenin at Thr556 to block its nuclear translocation. For the first time, HSV-1 US3 has been shown to inhibit IFN-I production

[Submit Query]

Powered by *OntoGPT*

## b
# Results

### genes

* **item: 1**:
  β-catenin <u>HGNC:2514</u>
* **item: 2**:
  US3 <u>HGNC:10420</u>
* **item: 3**:
  IFN <u>HGNC:5417</u>
* **item: 4**:
  ISG

### organisms

* **item: 1**:
  HSV-1 <u>NCBITaxon:10298</u>

### gene_organisms

* **item: 1**:
  * gene:
    β-catenin <u>HGNC:2514</u>
  * organism:
    HSV-1 <u>NCBITaxon:10298</u>
* **item: 2**:
  * gene:
    US3 <u>HGNC:10420</u>
  * organism:
    HSV-1 <u>NCBITaxon:10298</u>

### activities

* **item: 1**:
  transcription <u>GO:0006351</u>

Figure S1: Screenshot of web-ontogpt. (a) Form entry page, allowing selection of schema, plus input text. (b) Sample of results as structured object rendered as nested HTML. Note that both input text and results are truncated for brevity.

1

SPIRES

```mermaid
classDiagram
    class ChemicalToDiseaseDocument {
    }
    class Publication {
        string id
        string title
        string abstract
        string combined_text
        string full_text
    }
    class ChemicalToDiseaseRelationship {
        string qualifier
    }
    class Chemical {
        string id
        string label
    }
    class ChemicalToDiseasePredicate {
        string id
        string label
    }
    class Disease {
        string id
        string label
    }
    class NamedEntity {
        string id
        string label
    }

    ChemicalToDiseaseDocument "1" -- "*" ChemicalToDiseaseRelationship : triples
    ChemicalToDiseaseDocument "1" -- "1" Publication : publication
    ChemicalToDiseaseRelationship "*" -- "1" Chemical : subject
    ChemicalToDiseaseRelationship "*" -- "1" ChemicalToDiseasePredicate : predicate
    ChemicalToDiseaseRelationship "*" -- "1" Disease : object
    ChemicalToDiseaseRelationship "*" -- "1" NamedEntity : subject_qualifier
    ChemicalToDiseaseRelationship "*" -- "1" NamedEntity : object_qualifier
```

Figure S2: Chemical to Disease (CTD) schema (available from https://w3id.org/ontogpt/ctd).

Table S1: Resources used for grounding during evaluation of SPIRES with relations in the BC5CDR test corpus. These resources were used for initial annotation and are subsequently normalized to MeSH. Annotations from the Gilda text entity normalization tool are retrieved through its API (http://grounding.indra.bio/apidocs) using the Ontology Access Kit.


<table>
  <thead>
    <tr>
        <th>Entity type</th>
        <th>Resource</th>
        <th>Prefix</th>
        <th>Source</th>
    </tr>
  </thead>
  <tbody>
    <tr>
        <td rowspan="6">Chemical</td>
        <td>Medical Subject Headings 2022</td>
        <td>MESH</td>
        <td>[22]</td>
    </tr>
    <tr>
        <td>Chemical Entities of Biological Interest</td>
        <td>CHEBI</td>
        <td>[23]</td>
    </tr>
    <tr>
        <td>National Cancer Institute Thesaurus</td>
        <td>NCIT</td>
        <td>[56]</td>
    </tr>
    <tr>
        <td>Mapping of Drug Names and MeSH 2022</td>
        <td>MDM</td>
        <td>[22]</td>
    </tr>
    <tr>
        <td>DrugBank</td>
        <td>DRUGBANK</td>
        <td>[24]</td>
    </tr>
    <tr>
        <td>Gilda</td>
        <td>N/A</td>
        <td>[18]</td>
    </tr>
    <tr>
        <td rowspan="6">Disease</td>
        <td>Medical Subject Headings 2022</td>
        <td>MESH</td>
        <td>[22]</td>
    </tr>
    <tr>
        <td>Mondo Disease Ontology</td>
        <td>MONDO</td>
        <td>[57]</td>
    </tr>
    <tr>
        <td>Human Phenotype Ontology</td>
        <td>HP</td>
        <td>[58]</td>
    </tr>
    <tr>
        <td>National Cancer Institute Thesaurus</td>
        <td>NCIT</td>
        <td>[56]</td>
    </tr>
    <tr>
        <td>Human Disease Ontology</td>
        <td>DOID</td>
        <td>[59]</td>
    </tr>
    <tr>
        <td>Medical Dictionary for Regulatory Activities</td>
        <td>MEDDRA</td>
        <td>[25]</td>
    </tr>
  </tbody>
</table>

2

SPIRES

![Screenshot of extracted recipes in a merged OWL file from the Protege ontology editor.](page_19_image_1_v2.jpg)

Figure S3: Screenshot of extracted recipes in a merged OWL file from the Protege ontology editor [55]. The "Simple Spaghetti" recipe is correctly classified under MeatRecipe, due to the presence of an ingredient that is classified as a meat-based product in FOODON. The right hand panel shows OWL logical axioms for the recipe, including its ingredients, and the steps involved.

3

SPIRES

Table S2: MeSH identifiers used to define value sets during evaluation of SPIRES with relations in the BC5CDR test corpus. All identifiers in this table were treated as root nodes of a hierarchy, i.e., the value sets include all child MeSH terms.


<table>
  <thead>
    <tr>
        <th>Entity type</th>
        <th>MeSH identifier</th>
        <th>MeSH term</th>
    </tr>
  </thead>
  <tbody>
    <tr>
        <td rowspan="15">Chemical</td>
        <td>D602</td>
        <td>Amino Acids, Peptides, and Proteins</td>
    </tr>
    <tr>
        <td>D1685</td>
        <td>Biological Factors</td>
    </tr>
    <tr>
        <td>D2241</td>
        <td>Carbohydrates</td>
    </tr>
    <tr>
        <td>D4364</td>
        <td>Pharmaceutical Preparations</td>
    </tr>
    <tr>
        <td>D6571</td>
        <td>Heterocyclic Compounds</td>
    </tr>
    <tr>
        <td>D7287</td>
        <td>Inorganic Chemicals</td>
    </tr>
    <tr>
        <td>D8055</td>
        <td>Lipids</td>
    </tr>
    <tr>
        <td>D9706</td>
        <td>Nucleic Acids, Nucleotides, and Nucleosides</td>
    </tr>
    <tr>
        <td>D9930</td>
        <td>Organic Chemicals</td>
    </tr>
    <tr>
        <td>D11083</td>
        <td>Polycyclic Compounds</td>
    </tr>
    <tr>
        <td>D13812</td>
        <td>Therapeutics</td>
    </tr>
    <tr>
        <td>D19602</td>
        <td>Food and Beverages</td>
    </tr>
    <tr>
        <td>D45424</td>
        <td>Complex Mixtures</td>
    </tr>
    <tr>
        <td>D45762</td>
        <td>Enzymes and Coenzymes</td>
    </tr>
    <tr>
        <td>D46911</td>
        <td>Macromolecular Substances</td>
    </tr>
    <tr>
        <td rowspan="27">Disease</td>
        <td>D001423</td>
        <td>Bacterial Infections and Mycoses</td>
    </tr>
    <tr>
        <td>D001523</td>
        <td>Mental Disorders</td>
    </tr>
    <tr>
        <td>D002318</td>
        <td>Cardiovascular Diseases</td>
    </tr>
    <tr>
        <td>D002943</td>
        <td>Circulatory and Respiratory Physiological Phenomena</td>
    </tr>
    <tr>
        <td>D004066</td>
        <td>Digestive System Diseases</td>
    </tr>
    <tr>
        <td>D004700</td>
        <td>Endocrine System Diseases</td>
    </tr>
    <tr>
        <td>D005128</td>
        <td>Eye Diseases</td>
    </tr>
    <tr>
        <td>D005261</td>
        <td>Female Urogenital Diseases and Pregnancy Complications</td>
    </tr>
    <tr>
        <td>D006425</td>
        <td>Hemic and Lymphatic Diseases</td>
    </tr>
    <tr>
        <td>D007154</td>
        <td>Immune System Diseases</td>
    </tr>
    <tr>
        <td>D007280</td>
        <td>Disorders of Environmental Origin</td>
    </tr>
    <tr>
        <td>D009057</td>
        <td>Stomatognathic Diseases</td>
    </tr>
    <tr>
        <td>D009140</td>
        <td>Musculoskeletal Diseases</td>
    </tr>
    <tr>
        <td>D009358</td>
        <td>Congenital, Hereditary, and Neonatal Diseases and Abnormalities</td>
    </tr>
    <tr>
        <td>D009369</td>
        <td>Neoplasms</td>
    </tr>
    <tr>
        <td>D009422</td>
        <td>Nervous System Diseases</td>
    </tr>
    <tr>
        <td>D009750</td>
        <td>Nutritional and Metabolic Diseases</td>
    </tr>
    <tr>
        <td>D009784</td>
        <td>Occupational Diseases</td>
    </tr>
    <tr>
        <td>D010038</td>
        <td>Otorhinolaryngologic Diseases</td>
    </tr>
    <tr>
        <td>D010272</td>
        <td>Parasitic Diseases</td>
    </tr>
    <tr>
        <td>D012140</td>
        <td>Respiratory Tract Diseases</td>
    </tr>
    <tr>
        <td>D013568</td>
        <td>Pathological Conditions, Signs and Symptoms</td>
    </tr>
    <tr>
        <td>D014777</td>
        <td>Virus Diseases</td>
    </tr>
    <tr>
        <td>D014947</td>
        <td>Wounds and Injuries</td>
    </tr>
    <tr>
        <td>D017437</td>
        <td>Skin and Connective Tissue Diseases</td>
    </tr>
    <tr>
        <td>D052801</td>
        <td>Male Urogenital Diseases</td>
    </tr>
    <tr>
        <td>D064419</td>
        <td>Chemically-Induced Disorders</td>
    </tr>
  </tbody>
</table>

4

SPIRES

Table S3: Results for named entity recognition evaluation of SPIRES on chemical and disease entities in the BC5CDR corpus. The chunking strategy was not used in this evaluation. Grounding was performed against MeSH only - further accuracy may be afforded by use of alternate ontology annotators such as CHEBI or MONDO for chemical and disease, respectively.


<table>
  <thead>
    <tr>
        <th>Entity type</th>
        <th>Model</th>
        <th>F-score</th>
        <th>Precision</th>
        <th>Recall</th>
    </tr>
  </thead>
  <tbody>
    <tr>
        <td rowspan="2">Chemical</td>
        <td>GPT-3.5-turbo</td>
        <td>69.70</td>
        <td>0.89</td>
        <td>0.57</td>
    </tr>
    <tr>
        <td>GPT-4</td>
        <td>73.69</td>
        <td>0.85</td>
        <td>0.65</td>
    </tr>
    <tr>
        <td rowspan="2">Disease</td>
        <td>GPT-3.5-turbo</td>
        <td>61.70</td>
        <td>0.87</td>
        <td>0.48</td>
    </tr>
    <tr>
        <td>GPT-4</td>
        <td>69.70</td>
        <td>0.88</td>
        <td>0.56</td>
    </tr>
  </tbody>
</table>

5