#!/usr/bin/env python3
"""
    File name: viewnet.py
    Author: Leo Browning
    email: leobrowning92@gmail.com
    Date created: 02/09/2017 (DD/MM/YYYY)
    Python Version: 3.5
    Description:
    Helper module with all of the electrical information for netsim.py.
    Includes classes for the conducting elements (transistors, resistors, etc)
    and the conduction network class which actually solves the network for
    the current and voltage using multi nodal analysis (MNA)
"""

import argparse
import numpy as np
import networkx as nx
import scipy.sparse as sparse

class LinExpTransistor():
    def __init__(self,type,onoffmap=0):
        # m-s switching from G=1 to G=5e-5
        onoffmap0={'ms':0.5,'sm':0.5, 'mm':1e-5,'ss':1e-5,'vs':1e-5,'sv':1e-5,'vm':1e-5,'mv':1e-5}
        # m-s and electrode-s switching from G=1 to G=5e-5
        onoffmap1={'ms':0.5,'sm':0.5, 'mm':1e-5,'ss':1e-5,'vs':0.5,'sv':0.5,'vm':1e-5,'mv':1e-5}
        # m-s, s-s and electrode-s switching from G=1 to G=5e-5
        onoffmap2={'ms':0.5,'sm':0.5, 'mm':1e-5,'ss':0.5,'vs':0.5,'sv':0.5,'vm':1e-5,'mv':1e-5}
        onoffmappings=[onoffmap0,onoffmap1,onoffmap2]
        self.gate_voltage=0
        self.type=type
        self.alpha=onoffmappings[onoffmap][type]

    def lin_exp(self,vg):
        alpha=self.alpha
        # normalizes conduction at 1 for -10
        normalization=np.exp(-10*alpha)#
        return np.exp(-alpha*vg)*normalization
    def get_conductance(self):
        gate=self.gate_voltage
        G=self.lin_exp(gate)
        return G



class FermiDiracTransistor():
    """ uses a FD step function in VG to calculate conductance"""
    def __init__(self,type,onoffmap=0):
        #### preset onoffmappings  #####
        ### 0 ###
        # only intertube junctions have a 10^3 on off ratio
        #designed to match onoffmap from LinExpTransistor
        onoffmap0={'ms':1/5e-5,'sm':1/5e-5, 'mm':1,'ss':1,'vs':1,'sv':1,'vm':1,'mv':1}
        onoffmappings=[onoffmap0]

        self.offG=1/onoffmappings[onoffmap][type]
        self.scaling=1-self.offG
        self.offset=self.offG
        self.gate_voltage=0

    def _fermi_dirac(self,x,scaling,offset,threshold):
        return scaling*(1/(np.exp(10*(x-threshold))+1))+offset
    def get_conductance(self,gate=False):
        if gate:
            return self._fermi_dirac(gate, self.scaling, self.offset, 0)
        else:
            return self._fermi_dirac(self.gate_voltage, self.scaling, self.offset, 0)
class StepTransistor(object):
    def __init__(self,on_resistance=1,off_resistance=1000,threshold_voltage=0, gate_voltage=0):
        assert on_resistance>0 and off_resistance>0, "ERROR: a component cannot have -ve resistance"
        self.on_resistance=on_resistance
        self.off_resistance=off_resistance
        self.threshold_voltage=threshold_voltage
        self.gate_voltage=gate_voltage

    def get_conductance(self):
        if self.gate_voltage<=self.threshold_voltage:
            return 1/self.on_resistance
        else:
            return 1/self.off_resistance

class Resistor(object):
    def __init__(self,R=1):
        assert R>0, "ERROR: a component cannot have -ve resistance"
        self.resistance=R
        self.conductance=1/R
    def get_conductance(self):
        return self.conductance

class ConductionNetwork(object):
    """Solves for the conduction characteristics of a physical network"""
    def __init__(self,graph,ground_nodes,voltage_sources):
        self.graph=graph
        self.ground_nodes=np.array(ground_nodes)
        self.voltage_sources=np.array(voltage_sources)
        self.network_size=len(self.graph)
        self.gate_areas=[]
        self.vds=0.1

    def update_conductivity(self):
        for edge in self.graph.edges:
            G=self.graph.edges[edge]['component'].get_conductance()
            self.graph.edges[edge]['conductance']=G
            self.graph.edges[edge]['resistance']=1/G
    def make_G(self):
        """Generates the adjacency matrix of the graph as a numpy array and then sets the diagonal elements as the -ve sum of the conductances that attach to it.
        """
        G=nx.to_scipy_sparse_matrix(self.graph,nodelist=self.graph.nodes(),weight='conductance',format='lil')
        dsum=G.sum(axis=0)
        for i in range(self.network_size):
            G[i,i]=-dsum[0,i]
        return G
    def delete_sparse_rcs(self,mat,indices):
        row_mask = np.ones(mat.shape[0], dtype=bool)
        row_mask[indices] = False
        col_mask = np.ones(mat.shape[1], dtype=bool)
        col_mask[indices] = False
        return mat[row_mask][:,col_mask]
    def make_A(self, G):
        B=np.zeros((self.network_size,len(self.voltage_sources)))
        for i in range(self.network_size):
            if i in self.voltage_sources[:,0]:
                B[i,list(self.voltage_sources[:,0]).index(i)]=1
        D=np.zeros((len(self.voltage_sources),len(self.voltage_sources)))
        BTD=np.append(B.T,D,axis=1)
        A=sparse.hstack([G,B],format='lil')
        A=sparse.vstack([A,BTD],format='lil')
        A=self.delete_sparse_rcs(A,self.ground_nodes)
        return sparse.csr_matrix(A)
    def make_z(self):
        z = np.append(np.zeros((self.network_size-len(self.ground_nodes),1)), self.voltage_sources[:,1][:,None], axis=0)
        return np.array(z)
    def update_voltages(self,x):
        for i in self.ground_nodes:
            x=np.insert(x,i,0,axis=0)
        self.source_currents=x[-len(self.voltage_sources):]
        x=x[:-len(self.voltage_sources)]
        for i in range(len(self.graph.nodes)) :
            node=sorted(self.graph.nodes())[i]
            self.graph.nodes[node]['voltage']=float(x[i])
    def update_currents(self):
        for n1,n2 in self.graph.edges:
            g = float(self.graph.edges[n1,n2]['conductance'])
            dV = float(self.graph.nodes[n1]['voltage']) - float(self.graph.nodes[n2]['voltage'])
            # to include current directionality one would have to
            #replace the abs with some sort of node-node direction rules
            self.graph.edges[n1,n2]['current']= abs(g * dV)
    def solve_mna(self):
        mna_x=sparse.linalg.spsolve(self.make_A(self.make_G()), self.make_z())
        return mna_x
    def update(self,show=True,v=False):
        #process mna_x to seperate out relevant components
        self.update_conductivity()
        mna_x = self.solve_mna()
        self.update_voltages(mna_x)
        self.update_currents()
        pass


    def set_global_gate(self,voltage):
        for edge in self.graph.edges:
            self.graph.edges[edge]['component'].gate_voltage=voltage
    def set_local_gate(self,area,voltage):
        for edge in self.get_local_edges(area):
            self.graph.edges[edge]['component'].gate_voltage=voltage
        self.gate_areas.append([area,voltage])
    def check_in_area(self,point,area):
        """point is in [x,y], and area is [centerx,centery,xwidth,ylength]"""
        right=area[0]+area[2]/2
        left=area[0]-area[2]/2
        top=area[1]+area[3]/2
        bottom=area[1]-area[3]/2
        if left<=point[0]<=right and bottom<=point[1]<=top:
            return True
        else:
            return False
    def get_local_edges(self,area):
        local_edges=[]
        for edge in self.graph.edges:
            if self.check_in_area(self.graph.edges[edge]['pos'],area):
                local_edges.append(edge)
            else:
                pass
        return local_edges
