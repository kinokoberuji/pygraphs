from abc import ABC, abstractmethod
from collections import defaultdict

import networkx as nx
import numpy as np

from pygraphs.cluster import _kmeans_pytorch as _backend
from pygraphs.cluster.base import KernelEstimator


class KMeans_Fouss(KernelEstimator, ABC):
    def __init__(self, n_clusters, n_init=10, max_rerun=100, max_iter=100, init='any', init_measure='modularity',
                 random_state=42, device='cuda:0'):
        super().__init__(n_clusters, device=device, random_state=random_state)

        self.init_names = ['one', 'all', 'k-means++']
        self.eps = 10 ** -10

        self.n_init = n_init
        self.max_rerun = max_rerun
        self.max_iter = max_iter
        self.init = init
        self.init_measure = init_measure

    def fit(self, K, y=None, sample_weight=None):
        self.labels_ = self.predict(K)
        return self

    def _init_simple(self, K, init):
        n = K.shape[0]
        q_idx = np.arange(n)
        np.random.shuffle(q_idx)

        h = np.zeros((self.n_clusters, n), dtype=np.float64)
        if init == 'one':  # one: choose one node for each cluster
            for i in range(self.n_clusters):
                h[i, q_idx[i]] = 1.
        elif init == 'all':  # all: choose (almost) all nodes to clusters
            nodes_per_cluster = n // self.n_clusters
            for i in range(self.n_clusters):
                for j in range(i * nodes_per_cluster, (i + 1) * nodes_per_cluster):
                    h[i, q_idx[j]] = 1. / nodes_per_cluster
        else:
            raise NotImplementedError()
        return h

    def _init_h(self, K: np.array, init: str):
        if init in ['one', 'all']:
            h = self._init_simple(K, init=init)
        elif init == 'k-means++':
            h = _backend.kmeanspp(K, self.n_clusters, device=self.device)
        else:
            raise NotImplementedError()
        return h

    def _predict_successful_once(self, K: np.array, init_idx: int, init: str, G: nx.Graph = None):
        np.random.seed(self.random_state + init_idx)
        labels, quality = None, np.nan
        for _ in range(self.max_rerun):
            try:
                K = K.astype(np.float64)
                labels, inertia, success = self._predict_once(K, init)
                if success:
                    if self.init_measure == 'inertia':
                        quality = inertia
                    elif self.init_measure == 'modularity':
                        quality = -self._calc_modularity_slow(G, labels)
                    return labels, quality
            except Exception or ValueError or FloatingPointError or np.linalg.LinAlgError:
                pass
        return labels, quality

    @abstractmethod
    def _predict_once(self, K: np.array, init: str):
        pass

    def _calc_modularity_slow(self, G, labels):
        communities = defaultdict(list)
        for idx, label in enumerate(labels):
            communities[label].append(idx)
        communities = list(communities.values())
        return nx.community.modularity(G, communities)

    def predict(self, K, explicit=False, G: nx.Graph = None):
        inits, best_labels, best_inertia = [], None, np.inf
        init_names = self.init_names if self.init == 'any' else [self.init]
        for init in init_names:
            results = [self._predict_successful_once(K, i, init, G=G) for i in range(self.n_init)]
            for labels, inertia in results:
                if explicit:
                    inits.append({'labels': labels, 'inertia': inertia, 'init': init})
                else:
                    if inertia < best_inertia or best_labels is None:
                        best_inertia, best_labels = inertia, labels
        return inits if explicit else best_labels


class KKMeans(KMeans_Fouss):
    """Kernel K-means clustering
    Reference
    ---------
    Francois Fouss, Marco Saerens, Masashi Shimbo
    Algorithms and Models for Network Data and Link Analysis
    Algorithm 7.2: Simple kernel k-means clustering of nodes
    """

    name = 'KKMeans'

    def _predict_once(self, K: np.array, init: str):
        h_init = self._init_h(K, init)
        labels, inertia, is_ok = _backend.predict(K, h_init, self.max_iter, device=self.device)
        return labels, inertia, is_ok


class KKMeans_iterative(KMeans_Fouss):
    """Kernel K-means clustering
    Reference
    ---------
    Francois Fouss, Marco Saerens, Masashi Shimbo
    Algorithms and Models for Network Data and Link Analysis
    Algorithm 7.3: Simple iterative kernel k-means clustering of nodes
    """

    name = 'KKMeans_iterative'

    def _predict_once(self, K: np.array, init: str):
        h_init = self._init_h(K, init)
        labels, inertia, is_ok = _backend.iterative_predict(K, h_init, self.max_iter, self.eps, device=self.device)
        return labels, inertia, is_ok
