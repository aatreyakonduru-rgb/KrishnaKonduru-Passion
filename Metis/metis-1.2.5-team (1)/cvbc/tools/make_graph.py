"""Write ~/metis-work/graph.pkl ({'nodes','edges'}) from kb/CROSS-LAYER/LINK_GRAPH.yaml for the gallery builder."""
import os,pickle,yaml
W=os.environ.get('METIS_WORK',os.path.expanduser('~/metis-work'));K=os.environ.get('METIS_KB',W+'/kb')
g=yaml.load(open(K+'/CROSS-LAYER/LINK_GRAPH.yaml'),Loader=yaml.CSafeLoader)
pickle.dump({'nodes':g['nodes'],'edges':g['edges']},open(W+'/graph.pkl','wb'));print(len(g['nodes']),'nodes',len(g['edges']),'edges')
