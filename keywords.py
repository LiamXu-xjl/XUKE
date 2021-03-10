# The main logic of keyword extraction
import nltk
import networkx as nx
import numpy as np
import json
from nltk.stem import WordNetLemmatizer
from itertools import combinations
from queue import Queue
from collections import Counter
from MAG import MAG_get_abstracts

###### GLOBAL VARS #####
INCLUDE_POS = ['NN','NNS','JJ']       # Syntax Filters
CONVERGENCE_THRESHOLD = 0.0001  # Convergence threshold
CONVERGENCE_EPOCH_NUM = 50      # force stop after how many epochs
WINDOW_SIZE = 10    # window size used in graph building
DAMPING_FACTOR = 0.85   # damping factor used in graph building
KEYWORD_RATIO = 0.6     # how much keywords do we want to keep for each publication
SCALING = 1.0    # how strong a effect the year has on publication importance, the larger the stronger.
KEYWORD_LIST = json.load(open("cs_keyword_list.json", 'r')) # the keyword list for proper CS words

def keywords(text, ratio=KEYWORD_RATIO):

    # Sanity check
    if not isinstance(text, str):
        raise ValueError("Text parameter must be a string")
    
    # get the tokenized text, all lowercase
    tokenizer = nltk.RegexpTokenizer(r"\w+")
    tokenized_text = tokenizer.tokenize(text.lower())
    tokenized_text_with_punc = nltk.word_tokenize(text.lower())

    # filter out all the nouns and adjectives in filtered_text
    tagged_text = nltk.pos_tag(tokenized_text)
    filtered_unit = list(filter(lambda x : x[1] in INCLUDE_POS, tagged_text))
    filtered_text = [ x[0] for x in filtered_unit]
    token_pos_dict = {}
    token_lemma_dict = {}
    for x in filtered_unit:
        token_pos_dict[x[0]] = 'a' if x[1] == 'JJ' else 'n' 

    # build the graph
    text_graph = nx.Graph()
    for word in filtered_text:
        if word not in list(text_graph.nodes):
            text_graph.add_node(word)
    
    # set the graph edges with weights (1/2) first window
    lemmatizer = WordNetLemmatizer() # lemmatizer
    first_window = tokenized_text[:WINDOW_SIZE]
    for word1, word2 in combinations(first_window, 2):
        if word1 in filtered_text and word2 in filtered_text:
            word1_lemma = lemmatizer.lemmatize(word1,pos=token_pos_dict[word1])
            word2_lemma = lemmatizer.lemmatize(word2,pos=token_pos_dict[word2])
            text_graph.add_edge(word1_lemma,word2_lemma,weight=1)
            if word1 not in token_lemma_dict:
                token_lemma_dict[word1] = word1_lemma
            if word2 not in token_lemma_dict:
                token_lemma_dict[word2] = word2_lemma
    
    # set the graph edges with weights (2/2) next windows
    queue = Queue()
    current_window = []
    for i in first_window:
        queue.put(i)
        current_window.append(i)
    for i in range(WINDOW_SIZE, len(tokenized_text)):
        head = queue.get()
        current_window.remove(head)
        tail = tokenized_text[i]
        queue.put(tail)
        current_window.append(tail)
        for word1, word2 in combinations(current_window, 2):
            if word1 in filtered_text and word2 in filtered_text:
                word1_lemma = lemmatizer.lemmatize(word1,pos=token_pos_dict[word1])
                word2_lemma = lemmatizer.lemmatize(word2,pos=token_pos_dict[word2])
                text_graph.add_edge(word1_lemma,word2_lemma,weight=1)
                if word1 not in token_lemma_dict:
                    token_lemma_dict[word1] = word1_lemma
                if word2 not in token_lemma_dict:
                    token_lemma_dict[word2] = word2_lemma

    # conduct the page rank
    damping = DAMPING_FACTOR
    if (len(list(text_graph.nodes))==0):
        raise ValueError("Text is empty!")
    lemma_score_dict = dict.fromkeys(text_graph.nodes(), 1/len(list(text_graph.nodes)))
    for _ in range(CONVERGENCE_EPOCH_NUM):
        convergence_achieved = 0
        for i in text_graph.nodes:
            rank = 1 - damping
            for j in text_graph.adj[i]:
                neighbors_sum = sum(text_graph.edges[j, k]['weight'] for k in text_graph.adj[j])
                rank += damping * lemma_score_dict[j] * text_graph.edges[j,i]['weight'] / neighbors_sum
            if abs(lemma_score_dict[i] - rank) <= CONVERGENCE_THRESHOLD:
                convergence_achieved += 1
            lemma_score_dict[i] = rank
        if convergence_achieved == len(text_graph.nodes()):
            break

    candidates = list(lemma_score_dict.keys())
    candidates.sort(key=lambda w: lemma_score_dict[w], reverse=True)
    selected = candidates[:int(len(candidates)*KEYWORD_RATIO)]

    # combine keywords
    combined_list = []
    current_combination = []
    for token in tokenized_text_with_punc: 
        if token not in token_lemma_dict:
            if len(current_combination) != 0:
                if current_combination not in combined_list:
                    combined_list.append(current_combination)
                current_combination = []
            continue
        if token_lemma_dict[token] not in selected:
            if len(current_combination) != 0:
                if current_combination not in combined_list:
                    combined_list.append(current_combination)
                current_combination = []
            continue
        else: 
            current_combination.append(token)

    # output keywords
    keyword_score_dict = {}
    for comb in combined_list:
        # filter out single adjectives
        if len(comb) == 1 and token_pos_dict[comb[0]] == 'a':
            continue
        comb_lem = [lemmatizer.lemmatize(w.lower()) for w in comb]
        if any(item not in KEYWORD_LIST for item in comb_lem):
            continue
        keyword = ' '.join(comb)
        score = 0
        for word in comb: 
            score += lemma_score_dict[token_lemma_dict[word]]
        keyword_score_dict[keyword] = score

    return keyword_score_dict

def keywords_multiple(text_list, ratio=KEYWORD_RATIO):
    if not isinstance(text_list, list):
        raise ValueError('Input is not a list')
    years = [i for (_,i,_) in text_list]
    earliest = min(years)
    latest = max(years)
    citations = [i for (_,_,i) in text_list]
    least = min(citations)
    most = max(citations)

    final_cnt = Counter({})
    for idx, (text, year, citation) in enumerate(text_list):
        print('[keywords_multiple] Processing text ({} of {}).'.format(idx, len(text_list)))
        print('year: {}, citation:{}'.format(year, citation))
        year_score = 1 - (year-earliest)/(latest-earliest)
        citation_score = 1 - (citation-least)/(most-least)
        paper_scaling_factor = np.e**(-1 * year_score * citation_score * SCALING) # how paper_scaling_factor is calculated
        
        keyword_score_dict = keywords(text, ratio)
        
        keyword_score_dict_scaled = {k:v * paper_scaling_factor for k,v in keyword_score_dict.items()}
        current_cnt = Counter(keyword_score_dict_scaled)
        final_cnt = final_cnt + current_cnt

    final_keyword_score_dict = dict(final_cnt)
    
    return final_keyword_score_dict

def filter_abstracts(abstract_list, time_ratio):
    years = [i for (_,i,_) in abstract_list]
    earliest = min(years)
    latest = max(years)
    starting_year = int(earliest + time_ratio[0] * (latest-earliest))
    ending_year = int(earliest + time_ratio[1] * (latest-earliest))
    filtered_abstracts = [ab for ab in abstract_list if ab[1] >= starting_year and ab[1] <= ending_year]
    return filtered_abstracts, starting_year, ending_year





if __name__ == '__main__':
    TEST_1 = False
    TEST_2 = True

    # TEST_1: keyword_multiple with default texts
    if TEST_1:
        default_text_1 = "Graph is an important data representation which appears in a wide diversity of real-world scenarios. Effective graph analytics provides users a deeper understanding of what is behind the data, and thus can benefit a lot of useful applications such as node classification, node recommendation, link prediction, etc. However, most graph analytics methods suffer the high computation and space cost. Graph embedding is an effective yet efficient way to solve the graph analytics problem. It converts the graph data into a low dimensional space in which the graph structural information and graph properties are maximumly preserved. In this survey, we conduct a comprehensive review of the literature in graph embedding. We first introduce the formal definition of graph embedding as well as the related concepts. After that, we propose two taxonomies of graph embedding which correspond to what challenges exist in different graph embedding problem settings and how the existing work addresses these challenges in their solutions. Finally, we summarize the applications that graph embedding enables and suggest four promising future research directions in terms of computation efficiency, problem settings, techniques, and application scenarios."
        default_text_2 = "Witnessing the emergence of Twitter, we propose a Twitter-based Event Detection and Analysis System (TEDAS), which helps to (1) detect new events, to (2) analyze the spatial and temporal pattern of an event, and to (3) identify importance of events. In this demonstration, we show the overall system architecture, explain in detail the implementation of the components that crawl, classify, and rank tweets and extract location from tweets, and present some interesting results of our system."
        default_text_3 = "The Web has been rapidly \"deepened\" by the prevalence of databases online. With the potentially unlimited information hidden behind their query interfaces, this \"deep Web\" of searchable databses is clearly an important frontier for data access. This paper surveys this relatively unexplored frontier, measuring characteristics pertinent to both exploring and integrating structured Web sources. On one hand, our \"macro\" study surveys the deep Web at large, in April 2004, adopting the random IP-sampling approach, with one million samples. (How large is the deep Web? How is it covered by current directory services?) On the other hand, our \"micro\" study surveys source-specific characteristics over 441 sources in eight representative domains, in December 2002. (How \"hidden\" are deep-Web sources? How do search engines cover their data? How complex and expressive are query forms?) We report our observations and publish the resulting datasets to the research community. We conclude with several implications (of our own) which, while necessarily subjective, might help shape research directions and solutions."
        default_text_4 = "Users' locations are important to many applications such as targeted advertisement and news recommendation. In this paper, we focus on the problem of profiling users' home locations in the context of social network (Twitter). The problem is nontrivial, because signals, which may help to identify a user's location, are scarce and noisy. We propose a unified discriminative influence model, named as UDI, to solve the problem. To overcome the challenge of scarce signals, UDI integrates signals observed from both social network (friends) and user-centric data (tweets) in a unified probabilistic framework. To overcome the challenge of noisy signals, UDI captures how likely a user connects to a signal with respect to 1) the distance between the user and the signal, and 2) the influence scope of the signal. Based on the model, we develop local and global location prediction methods. The experiments on a large scale data set show that our methods improve the state-of-the-art methods by 13%, and achieve the best performance."
        default_text_list = [default_text_1, default_text_2, default_text_3, default_text_4]
        final_keyword_score_dict = keywords_multiple(default_text_list)
        print(final_keyword_score_dict)
    
    # TEST_2: keyword_multiple with MAG APIs
    if TEST_2: 
        abstract_list = MAG_get_abstracts('University of Illinois at Urbana Champaign','Kevin Chenchuan Chang')
        abs_ = [ab[0] for ab in abstract_list]
        final_keyword_score_dict = keywords_multiple(abstract_list, 0.3)
        print(final_keyword_score_dict)

