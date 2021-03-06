import theano
import sklearn
import sklearn.metrics
import numpy as np
import itertools
from numpy import *	#zeros(..)
import theano.tensor as T
import theano.tensor.nnet as nnet
#from train import Feature_group_list
from lookup_table import Lookup_table
from compiler.ast import flatten
from feature_group_list import Feature_group_list
import pycuda.gpuarray as gpuarray
import pycuda.driver as cuda
import pycuda.autoinit
from pycuda.compiler import SourceModule
import time
class CNN:
	def __init__(self,input_groupid,lookup_table,pattern_groupid_list):
		self.input_nodenum = input_groupid*lookup_table.embedding_length
		
		mu = 0
		sigm = 0.1
		self.k_size = 3
		self.hid1_nodenum = 400
		self.hid2_nodenum = 100
		self.output_nodenum = 2
				
		self.theta1 = gpuarray.to_gpu( np.random.normal(mu,sigm,self.input_nodenum*self.hid1_nodenum).reshape(self.input_nodenum,self.hid1_nodenum).astype(np.float32) )
		self.b1 = gpuarray.to_gpu( np.random.normal(mu,sigm,self.hid1_nodenum).reshape(1,self.hid1_nodenum).astype(np.float32) )
		self.theta2 = gpuarray.to_gpu( np.random.normal(mu,sigm,self.hid1_nodenum*self.hid2_nodenum).reshape(self.hid1_nodenum,self.hid2_nodenum).astype(np.float32) )
		self.b2 =  gpuarray.to_gpu( np.random.normal(mu,sigm,self.hid2_nodenum).reshape(1,self.hid2_nodenum).astype(np.float32) )
		self.theta3 = gpuarray.to_gpu( np.random.normal(mu,sigm,self.hid2_nodenum*self.output_nodenum).reshape(self.hid2_nodenum,self.output_nodenum).astype(np.float32) )
		self.b3 =  gpuarray.to_gpu( np.random.normal(mu,sigm,self.output_nodenum).reshape(1,self.output_nodenum).astype(np.float32) )
		self.vs = gpuarray.to_gpu( np.random.randn(self.hid2_nodenum,self.k_size).astype(np.float32) )	
		
		'''
		self.theta1 = gpuarray.to_gpu( np.ones(self.input_nodenum*self.hid1_nodenum).reshape(self.input_nodenum,self.hid1_nodenum).astype(np.float32) )
		self.b1 = gpuarray.to_gpu( np.ones(self.hid1_nodenum).reshape(1,self.hid1_nodenum).astype(np.float32) )
		self.theta2 = gpuarray.to_gpu( np.ones(self.hid1_nodenum*self.hid2_nodenum).reshape(self.hid1_nodenum,self.hid2_nodenum).astype(np.float32) )
		self.b2 =  gpuarray.to_gpu( np.ones(self.hid2_nodenum).reshape(1,self.hid2_nodenum).astype(np.float32) )
		self.theta3 = gpuarray.to_gpu( np.ones(self.hid2_nodenum*self.output_nodenum).reshape(self.hid2_nodenum,self.output_nodenum).astype(np.float32) )
		self.b3 =  gpuarray.to_gpu( np.ones(self.output_nodenum).reshape(1,self.output_nodenum).astype(np.float32) )
		self.vs = gpuarray.to_gpu( np.random.randn(self.hid2_nodenum,self.k_size).astype(np.float32) )	
		'''
		self.lamda = 0.1
		self.alpha = 0.001
		self.MAX_Threads_EachBlock_NUM = 800
		self.MAX_ThreadBlock_Height = 20
		self.MAX_ThreadBlock_Width = 20
#		FM model V matrix also theano.shared()
#		self.table_list = theano.shared(lookup_table.table_list)
		self.lookup_table = lookup_table
		self.pattern_group_id_list = pattern_groupid_list

#self.cost
	def layer(self,x,w,b):
		new_x = x
#		m = T.dot(new_x,w)
#		h = nnet.sigmoid(m)
		h = nnet.sigmoid(T.dot(new_x,w)+b) 
		return h
	def hid2_to_output(self,x,w,b,vs):
		y = T.dot(x,w)+b
		'''
		W = T.dot(vs,vs.T)
		for i in range(self.hid2_nodenum-1):
			for j in range(i+1,self.hid2_nodenum):
				y += W[i][j]*x[:,i]*x[:,j]
		'''
		out = nnet.softmax(y)
		
#		out = nnet.softmax(T.dot(x,w)+b)
		return out

	def grad_desc(self,cost,theta):
	#	self.cost = cost
		return theta-(self.alpha*T.grad(cost,wrt=theta))


	def load_data(self,batch_index,origin_batchsize,batchsize):
		instance_begin = batch_index*origin_batchsize
		instance_end = instance_begin + batchsize
		list_feature_batch = self.feature_group_list.list_feature[instance_begin:instance_end]
		list_group_batch = self.feature_group_list.list_group[instance_begin:instance_end]
		list_target_batch = self.feature_group_list.list_target[instance_begin:instance_end]
		input_dim = self.feature_group_list.input_groupid*self.lookup_table.embedding_length

#		trainx = gpuarray.to_gpu( np.zeros((batchsize,input_dim)).astype(np.float32) )
		
		trainx = np.zeros((batchsize,input_dim)).astype(np.float32)

		vec_length = self.lookup_table.embedding_length
		for i in xrange(batchsize): 
			instance_fea = list_feature_batch[i]
			instance_gro = list_group_batch[i]
			for groupid_incre in xrange(len(instance_gro)):
				groupid = instance_gro[groupid_incre]
				featureid = instance_fea[groupid_incre]
				pos = self.lookup_table.QueryPos(groupid,featureid)
				offset = self.lookup_table.groupid_offset[groupid]
					
				trainx[i][offset:offset+vec_length] = trainx[i][offset:offset+vec_length] + self.lookup_table.central_array[pos:pos+vec_length]

		
		#trainx = gpuarray.to_gpu(trainx)
		trainy = np.array(list_target_batch)

		return [(trainx,trainy,list_feature_batch,list_group_batch)]

	def load_test_data(self):
		[(testx,testy)] = self.load_data()	
		return [(testx,testy)]
	def compute_ad_bucket(self,list_feature):
		ad_type = list_feature[0]
		has_img = list_feature[1]
		has_link = list_feature[2]
		ad_pos = list_feature[3]
		return "%s_%s_%s_%s"%(ad_type,has_img,has_link,ad_pos)


	def test_AUC(self,testx,testy,list_feature_batch):
		mod = SourceModule(
		"""
		__global__ void mat_X_mul_Wb(float* z,float* x, float* y,int* x_width,int* y_width,float* b)
		{
			int t_idx = threadIdx.x;
			int idx = (blockDim.x*blockIdx.x) + t_idx;
			float sum = 0;
			int xw = x_width[0];
			int yw = y_width[0];
			for(int e=0;e<xw;e++)
			{
				sum += x[idx/yw*xw+e]*y[yw*e+t_idx];
			}
			sum += b[t_idx];
			z[idx] = sum;

		}

		__global__ void mat_mul(float* z,float* x, float* y,int* x_width,int* y_width)
		{
			int t_idx = threadIdx.x;
			int idx = (blockDim.x*blockIdx.x) + t_idx;
			float sum = 0;
			int xw = x_width[0];
			int yw = y_width[0];
			for(int e=0;e<xw;e++)
			{
				sum += x[idx/yw*xw+e]*y[yw*e+t_idx];
			}
			z[idx] = sum;
		}
		__global__ void sigmoid(float* arr)
		{
			int t_idx = threadIdx.x;
			int idx = t_idx + (blockIdx.x * blockDim.x);
			arr[idx] = 1.0/(1+exp(-arr[idx]));
		}
		__global__ void calc_out_sum(float* out_sum,float* out,int* remainders)
		{
			int t_idx = threadIdx.x;
			int idx = (blockDim.x*blockIdx.x) + t_idx;
			int remainder = remainders[0];
			float sum = 0;
			int upper_value = blockDim.x*(gridDim.x-1) + remainder;
			if(idx<upper_value)
			{
				for(int e=0;e<2;e++)
				{
					sum += exp( out[idx*2+e] );  
				}
				out_sum[idx] = sum;
			}
		}
		__global__ void softmax(float* arr,float* arr_sum,int* remainders)
		{
			int t_idx = threadIdx.x;
			int idx = (blockDim.x*blockIdx.x) + t_idx;
			int remainder = remainders[0];
			int upper_value = blockDim.x*(gridDim.x-1) + remainder;
			if(idx<upper_value)
			{
				for(int e=0;e<2;e++)
				{
					arr[idx*2+e] = exp( arr[idx*2+e]  )/arr_sum[idx];
				}
			}
		}

		__global__ void pred_value(int* pred_label_gpu , float* layer3_out , int* remainders )
		{
			int t_idx = threadIdx.x;
			int idx = (blockDim.x*blockIdx.x) + t_idx;
			int remainder = remainders[0];
			int upper_value = blockDim.x*(gridDim.x-1) + remainder;
			if(idx<upper_value)
			{
				if( layer3_out[idx*2]<layer3_out[idx*+1] )
				{
					pred_label_gpu[idx] = 1;
				}
			}

		}

		"""
		)
		'''
			int upper_value = blockDim.x*(gridDim.x-1) + remainder;
			if(idx<upper_value)
			{

			}
		'''
		mat_X_mul_Wb = mod.get_function("mat_X_mul_Wb")
		mat_mul = mod.get_function("mat_mul")
		sigmoid = mod.get_function("sigmoid")
		softmax = mod.get_function("softmax")
		calc_out_sum = mod.get_function("calc_out_sum")
		pred_value = mod.get_function("pred_value")

		confuse_matrix = np.zeros((2,2))
		batchsize = len(testy)
		testx = gpuarray.to_gpu(testx)
		testy = gpuarray.to_gpu(testy.astype(np.int32))

#		hid1 = gpuarray.zeros((batchsize,self.hid1_nodenum),np.float32)
		hid1 = gpuarray.to_gpu(np.zeros((batchsize,self.hid1_nodenum)).astype(np.float32))
		xw_gpu = gpuarray.to_gpu(np.array([self.input_nodenum]).astype(np.int32))
		yw_gpu = gpuarray.to_gpu(np.array([self.hid1_nodenum]).astype(np.int32))
		mat_X_mul_Wb(hid1 , testx , self.theta1 , xw_gpu , yw_gpu , self.b1 , block=(self.theta1.shape[1],1,1) , grid=(batchsize,1) ) #+ self.b1
		sigmoid(hid1,block=(self.hid1_nodenum,1,1),grid=(batchsize,1))
		xw_gpu.gpudata.free()
		yw_gpu.gpudata.free()
		


#		hid2 = gpuarray.zeros((batchsize,self.hid2_nodenum),np.float32)
		hid2 = gpuarray.to_gpu(np.zeros((batchsize,self.hid2_nodenum)).astype(np.float32))
		xw_gpu = gpuarray.to_gpu(np.array([self.hid1_nodenum]).astype(np.int32))
		yw_gpu = gpuarray.to_gpu(np.array([self.hid2_nodenum]).astype(np.int32))
		mat_X_mul_Wb(hid2 , hid1 , self.theta2 , xw_gpu , yw_gpu , self.b2 , block=(self.theta2.shape[1],1,1) , grid=(hid1.shape[0],1) ) #+ self.b2
		sigmoid(hid2,block=(self.hid2_nodenum,1,1),grid=(batchsize,1))
		xw_gpu.gpudata.free()
		yw_gpu.gpudata.free()


#		out = gpuarray.zeros((batchsize,self.output_nodenum),np.float32)
		out = gpuarray.to_gpu(np.zeros((batchsize,self.output_nodenum)).astype(np.float32))
		xw_gpu = gpuarray.to_gpu(np.array([self.hid2_nodenum]).astype(np.int32))
		yw_gpu = gpuarray.to_gpu(np.array([self.output_nodenum]).astype(np.int32))
		mat_X_mul_Wb(out , hid2 , self.theta3 , xw_gpu , yw_gpu , self.b3  , block=(self.theta3.shape[1],1,1) , grid=(hid2.shape[0],1) ) #+ self.b3
		
		xw_gpu.gpudata.free()
		yw_gpu.gpudata.free()

		out_sum = gpuarray.zeros((batchsize,1),np.float32)
		'''
		explation:
		because testSet is larger,batchsize will be scalar.maybe batchsize will over the ability of cuda's MAX_THREADS_NUM of each block;
		Therefore,must calculate grid and block.
		'''
		quotient,remainder = divmod(batchsize,self.MAX_Threads_EachBlock_NUM)		
		remainds = gpuarray.to_gpu(np.array([remainder]).astype(np.int32))
		calc_out_sum(out_sum , out , remainds , block=(self.MAX_Threads_EachBlock_NUM,1,1) , grid=(quotient+1,1))
		softmax(out , out_sum , remainds , block=(self.MAX_Threads_EachBlock_NUM,1,1) , grid=(quotient+1,1))
#		calc_out_sum(out_sum , out , remainds , block=(400,1,1) , grid=(400,1))
#		softmax(out , out_sum , remainds , block=(400,1,1) , grid=(400,1))



		label = testy.get()
		batchsize = len(label)

		layer3_out_value = out.get()
		print 'predicted :'
		print layer3_out_value


		for value in layer3_out_value:
			self.pred_value_file.write("%s\n"%(value[1]))
		auc = 0.85
		"""

		auc = sklearn.metrics.roc_auc_score(testy.get(),(layer3_out_value)[:,1])
		'''
		print 'y_pred:'
		y_pred = (T.argmax(layer3_out_value,axis=1)).eval()
		print y_pred
		'''
		pred_label_gpu = gpuarray.zeros((batchsize,1),np.int32)
		pred_value(pred_label_gpu , out , remainds , block=(self.MAX_Threads_EachBlock_NUM,1,1) , grid=(quotient+1,1))
#		pred_value(pred_label_gpu , layer3_out , remainds , block=(400,1,1) , grid=(400,1))

		pred_label = pred_label_gpu.get()
		print 'confuse_matrix:'
		for i in xrange(batchsize):
			t = int( label[i] )
			t_pred = int( pred_label[i] )
			confuse_matrix[t][t_pred] += 1
		print confuse_matrix
		'''
		print 'log_loss:'
		log_loss = -T.mean( T.log(layer3_out[:,1])*testy + T.log(1-layer3_out[:,1])*(1-testy)  )
		print log_loss.eval()
		'''

#		accordding to ad_pos,to compute AUC..................
		pos_bucket = {}
		pos_bucket_label = {}
		for i in range(len(label)):
			ad_bucket = self.compute_ad_bucket(list_feature_batch[i])
			if ad_bucket not in pos_bucket.keys():
				pos_bucket[ad_bucket] = []
				pos_bucket_label[ad_bucket] = []
			pos_bucket[ad_bucket].append(layer3_out_value[i,1])
			pos_bucket_label[ad_bucket].append(label[i])
			
		for k in pos_bucket.keys():
			ad_labels = pos_bucket_label[k]
			if int( sum(ad_labels) ) == 0:
				print "ad_pos:%s,each label is 0!can't compute auc."%(k)
				continue
			pos_auc = sklearn.metrics.roc_auc_score(ad_labels,pos_bucket[k])
			print "pos:%s,instance_count:%s,auc:%s"%(k,len(ad_labels),pos_auc)

		"""

		testx.gpudata.free()
		testy.gpudata.free()
		hid1.gpudata.free()
		hid2.gpudata.free()
		out.gpudata.free()
		out_sum.gpudata.free()
		remainds.gpudata.free()
#		pred_label_gpu.gpudata.free()
	
		return auc

	def get_posibility(self,x):
		hid1 = self.layer(x,self.theta1,self.b1) #return a matrix
		hid2 = self.layer(hid1,self.theta2,self.b2) #return a matrix 
		out = self.hid2_to_output(hid2,self.theta3,self.b3,self.vs)  #return a matrix(|batchsize|*2)
		print 'get_posibility'
		return out #return a matrix(batchsize*2)

	def cost(self,x,y):
		hid1 = self.layer(x,self.theta1,self.b1) #return a matrix
		hid2 = self.layer(hid1,self.theta2,self.b2) #return a matrix 
		out1 = self.hid2_to_output(hid2,self.theta3,self.b3,self.vs)  #return a matrix(|batchsize|*2)



		batch_size=100
		return -T.mean( T.log(out1[:,1]*y+out1[:,0]*(1-y)) )

	def train(self,batchsize,trainx,trainy,list_feature_batch,list_group_batch):

		mod = SourceModule(
		
		"""	
		__global__ void sigmoid(float* arr)
		{
			int t_idx = threadIdx.x;
			int idx = t_idx + (blockIdx.x * blockDim.x);
			arr[idx] = 1.0/(1+exp(-arr[idx]));
		}
		__global__ void calc_out_sum(float* out_sum,float* out)
		{
			int t_idx = threadIdx.x;
			int idx = (blockDim.x*blockIdx.x) + t_idx;
			float sum = 0;
			for(int e=0;e<2;e++)
			{
				sum += exp( out[idx*2+e] );  
			}
			out_sum[idx] = sum;
		}
		__global__ void softmax(float* arr,float* arr_sum)
		{
				int t_idx = threadIdx.x;
				int idx = (blockDim.x*blockIdx.x) + t_idx;
				for(int e=0;e<2;e++)
				{
					arr[idx*2+e] =  exp( arr[idx*2+e] )/arr_sum[idx];
				}
		}
		__global__ void mat_X_mul_Wb(float* z,float* x, float* y,int x_width,int y_width,float* b)
		{
			int t_idx = threadIdx.x;
			int idx = (blockDim.x*blockIdx.x) + t_idx;
			float sum = 0;
			int xw = x_width;
			int yw = y_width;
			for(int e=0;e<xw;e++)
			{
				sum += x[idx/yw*xw+e]*y[yw*e+t_idx];
			}
			sum += b[t_idx];
			z[idx] = sum;

		}
		__global__ void mat_mul(float* z,float* x, float* y,int x_width,int y_width)
		{
			int t_idx = threadIdx.x;
			int idx = (blockDim.x*blockIdx.x) + t_idx;
			float sum = 0;
			int xw = x_width;
			int yw = y_width;
			for(int e=0;e<xw;e++)
			{
				sum += x[idx/yw*xw+e]*y[yw*e+t_idx];
			}
			z[idx] = sum;
		}
		__global__ void BigCOLMatrix_mul(float* z,float* x, float* y,int x_height,int x_width,int y_width,int line_remainders)
		{
			int idx = (blockIdx.x*blockDim.x) + threadIdx.x;
			int idy = (blockIdx.y*blockDim.y) + threadIdx.y;
			int eachLineRemaindNum = line_remainders;
			int thread_idx = ((gridDim.x*blockDim.x-eachLineRemaindNum )*idy) + idx;
			float sum = 0;
			int xw = x_width;
			int yw = y_width;
			int xHeight = x_height;
			if(idx<yw && idy<xHeight)
			{
				for(int e=0;e<xw;e++)
				{
					sum += x[thread_idx/yw*xw+e]*y[yw*e+idx];
				}
				z[thread_idx] = sum;
			}
		}

		__global__ void BigLineMatrix_transpose(float* a_t,float* a,int rows,int cols,int line_remainders)
		{
			int idx = (blockIdx.x*blockDim.x) + threadIdx.x;
			int idy = (blockIdx.y*blockDim.y) + threadIdx.y;
			int eachLineRemaindNum = line_remainders;
			int cols_num = cols;
			int rows_num = rows;
			int thread_idx = ((gridDim.x*blockDim.x-eachLineRemaindNum)*idy) + idx;
			int sz_row = thread_idx/cols_num;
			int sz_col = thread_idx%cols_num;
			if(idx<cols_num)
			{
			a_t[thread_idx] = a[sz_row+sz_col * rows_num];
			}


		}
		__global__ void matrix_transpose(float* a_t,float* a)
		{
			int t_idx = threadIdx.x;
			int idx = (blockDim.x*blockIdx.x) + t_idx;
			int row = gridDim.x;
			int col = blockDim.x;
			int sz_row = idx/col;
			int sz_col = idx%col;
			a_t[idx] = a[sz_row+sz_col*row];
		}

		"""
		
		)
		sigmoid = mod.get_function("sigmoid")
		softmax = mod.get_function("softmax")
		calc_out_sum = mod.get_function("calc_out_sum")
		mat_mul = mod.get_function("mat_mul")
		mat_X_mul_Wb = mod.get_function("mat_X_mul_Wb")
		BigCOLMatrix_mul = mod.get_function("BigCOLMatrix_mul")
		matrix_transpose = mod.get_function("matrix_transpose")
		BigLineMatrix_transpose = mod.get_function("BigLineMatrix_transpose")


		trainx = gpuarray.to_gpu(trainx)
		trainy = gpuarray.to_gpu(trainy.astype(np.float32))
#		forward............
		self.bias_one = gpuarray.to_gpu(np.ones((batchsize,1)).astype(np.float32))


		hid1 = gpuarray.zeros((batchsize,self.hid1_nodenum),np.float32)
		xw = np.int32(self.input_nodenum)
		yw = np.int32(self.hid1_nodenum)
		mat_X_mul_Wb(hid1 , trainx , self.theta1 , xw , yw , self.b1 , block=(self.theta1.shape[1],1,1) , grid=(batchsize,1) ) #+ self.b1
		sigmoid(hid1,block=(self.hid1_nodenum,1,1),grid=(batchsize,1))

		hid2 = gpuarray.zeros((batchsize,self.hid2_nodenum),np.float32)
		xw = np.int32(self.hid1_nodenum)
		yw = np.int32(self.hid2_nodenum)
		mat_X_mul_Wb(hid2 , hid1 , self.theta2 , xw , yw , self.b2 , block=(self.theta2.shape[1],1,1) , grid=(hid1.shape[0],1) ) #+ self.b2
		sigmoid(hid2,block=(self.hid2_nodenum,1,1),grid=(batchsize,1))

		out = gpuarray.zeros((batchsize,self.output_nodenum),np.float32)
		xw = np.int32(self.hid2_nodenum)
		yw = np.int32(self.output_nodenum)
		mat_X_mul_Wb(out , hid2 , self.theta3 , xw , yw , self.b3  , block=(self.theta3.shape[1],1,1) , grid=(hid2.shape[0],1) ) #+ self.b3


		#FM model solve Forward............................
		'''
		for i in range(self.hid2_nodenum-1):
			for j in range(i+1,self.hid2_nodenum):
				out += T.dot(self.vs[i],self.vs[j]) * layer2_out[:,i] * layer2_out[:,j]
		'''
		out_sum = gpuarray.zeros((batchsize,1),np.float32)
		calc_out_sum(out_sum , out , block=(batchsize,1,1) , grid=(1,1))
		softmax(out , out_sum , block=(batchsize,1,1) , grid=(1,1))

		
#		devirative...............
		output = np.zeros((batchsize,self.output_nodenum))
		#target = trainy.get()
		for i in xrange(batchsize):
			t = trainy[i]
			t = int(t.get())
			output[i][t] = 1
		output = gpuarray.to_gpu( output.astype(np.float32) )
		output = output - out
		
		delta2 = gpuarray.zeros((self.output_nodenum,self.hid2_nodenum),np.float32)
		xw = np.int32(batchsize)
		yw = np.int32(self.hid2_nodenum)
		output_t = gpuarray.zeros((output.shape[1],output.shape[0]),np.float32)
		matrix_transpose(output_t,-output,block=(output.shape[0],1,1),grid=(output.shape[1],1))

		mat_mul(delta2 , output_t , hid2 , xw , yw , block=(self.hid2_nodenum,1,1) , grid=(self.output_nodenum,1)) #delta2 shape:(2,batchsize)*(batchsize,100)->(2,100)

		theta3_delta =   -self.alpha * (delta2.T)
	
#		FM model solve Derivative............................
		'''
		o = output[:,0]
		matrix = layer2_out
		vs_delta = np.zeros((self.hid2_nodenum,self.k_size))
#		vs_delta = T.matrix('vs_delta')
		for l in xrange(self.hid2_nodenum):
			x = matrix[:,l]
			vector = -o * x
			for f in xrange(self.k_size):
				
				new_vs_vec = T.concatenate( [self.vs[0:l,f],self.vs[l+1:,f]],axis=0 )
				new_matrix = T.concatenate( [matrix[0:l,:],matrix[l+1:,:]],axis=0 )
				vec = T.dot(new_vs_vec.T,new_matrix)
				#vs_delta[l,f] = T.cast( T.dot(vector.T,vec.T),'floatX' )
				vs_delta[l,f] = 0

		self.vs.set_value(self.vs.get_value() + vs_delta)
		'''

		

		delta_tmp = gpuarray.zeros((self.output_nodenum,1),np.float32)
		xw = np.int32(batchsize)
		yw = np.int32(1)

		mat_mul(delta_tmp , output_t , self.bias_one , xw , yw , block=(1,1,1) , grid=(self.output_nodenum,1))
		b3_delta =  -self.alpha * delta_tmp.T 


		xw = np.int32(self.output_nodenum)
		yw = np.int32(self.hid2_nodenum)

		factor1 = gpuarray.zeros((batchsize,self.hid2_nodenum),np.float32)
		theta3_t = gpuarray.zeros((self.theta3.shape[1],self.theta3.shape[0]),np.float32)
		matrix_transpose(theta3_t,self.theta3,block=(self.theta3.shape[0],1,1),grid=(self.theta3.shape[1],1))

		mat_mul(factor1 , output , theta3_t , xw , yw , block=(self.hid2_nodenum,1,1) , grid=(batchsize,1))
		factor1 = (factor1.__mul__( hid2 )).__mul__( (1 - hid2) )

		
		xw = np.int32(batchsize)
		yw = np.int32(self.hid1_nodenum)

		delta1 = gpuarray.zeros((self.hid2_nodenum,self.hid1_nodenum),np.float32)
		factor1_t = gpuarray.zeros((factor1.shape[1],factor1.shape[0]),np.float32)
		matrix_transpose(factor1_t,-factor1,block=(factor1.shape[0],1,1),grid=(factor1.shape[1],1))

		mat_mul(delta1 , factor1_t , hid1 , xw , yw , block=(self.hid1_nodenum,1,1) ,grid=(self.hid2_nodenum,1)) #delta1 shape:(100,batchsize)*(batchsize,400)->(100,400)
		theta2_delta = -self.alpha * delta1.T 


		xw = np.int32(batchsize)
		yw = np.int32(1)

		delta1_bias = gpuarray.zeros((self.hid2_nodenum,1),np.float32)
		mat_mul(delta1_bias , factor1_t , self.bias_one , xw , yw , block=(1,1,1) , grid=(self.hid2_nodenum,1))
		b2_delta = -self.alpha * delta1_bias.T 




		xw = np.int32(self.hid2_nodenum)
		yw = np.int32(self.hid1_nodenum)

		factor0 = gpuarray.zeros((batchsize,self.hid1_nodenum),np.float32)
		theta2_t = gpuarray.zeros((self.theta2.shape[1],self.theta2.shape[0]),np.float32)
		matrix_transpose(theta2_t,self.theta2,block=(self.theta2.shape[0],1,1),grid=(self.theta2.shape[1],1))

		mat_mul(factor0 , factor1 , theta2_t ,  xw , yw , block=(self.hid1_nodenum,1,1) , grid=(batchsize,1))
		factor0 = ( factor0.__mul__( hid1)).__mul__(  (1 - hid1) )

		xw = np.int32(batchsize)
		xh = np.int32(self.hid1_nodenum)
		yw = np.int32(self.input_nodenum)
		
		delta0 = gpuarray.zeros((self.hid1_nodenum,self.input_nodenum),np.float32)
		factor0_t = gpuarray.zeros((factor0.shape[1],factor0.shape[0]),np.float32)
		matrix_transpose(factor0_t,-factor0,block=(factor0.shape[0],1,1),grid=(factor0.shape[1],1))

		line_quotient,line_remainder = divmod(self.input_nodenum,self.MAX_ThreadBlock_Width)
		if line_remainder!=0:
			line_quotient += 1
		line_remainder = np.int32(line_remainder)
		col_quotient,col_remainder = divmod(self.hid1_nodenum,self.MAX_ThreadBlock_Height)
		if col_remainder!=0:
			col_quotient += 1
		
		BigCOLMatrix_mul(delta0,factor0_t,trainx,xh,xw,yw,line_remainder,block=(self.MAX_ThreadBlock_Width,self.MAX_ThreadBlock_Height,1),grid=(line_quotient,col_quotient))


		'''
		mat_mul(delta0 , factor0_t , trainx , xw_gpu , yw_gpu , block=(self.input_nodenum,1,1) , grid=(self.hid1_nodenum,1)) #delta0 shape:(400,100)*(100,950)->(400,950)
		'''
		theta1_delta = -self.alpha * delta0.T


		xw = np.int32(self.hid2_nodenum)
		yw = np.int32(1)
		delta0_bias = gpuarray.zeros((self.hid1_nodenum,1),np.float32)
		mat_mul(delta0_bias , factor0_t , self.bias_one , xw , yw , block=(1,1,1) , grid=(self.hid1_nodenum,1))  #b1_delta shape:(400,batchsize)*(batchsize,1)->(400,1)
		b1_delta =  -self.alpha * delta0_bias.T  
		
		

		xw = np.int32(self.hid1_nodenum)
		xh = np.int32(batchsize)
		yw = np.int32(self.input_nodenum)

		delta_x = gpuarray.zeros((self.hid2_nodenum,self.input_nodenum),np.float32)



		theta1_t = gpuarray.zeros((self.theta1.shape[1],self.theta1.shape[0]),np.float32)


		line_quotient,line_remainder = divmod(self.input_nodenum,self.MAX_ThreadBlock_Width)
		if line_remainder!=0:
			line_quotient += 1
		col_quotient,col_remainder = divmod(self.hid1_nodenum,self.MAX_ThreadBlock_Width)
		if col_remainder!=0:
			col_quotient += 1
		rows = np.int32(self.hid1_nodenum)
		cols = np.int32(self.input_nodenum)

		line_remainder = np.int32(line_remainder)
		BigLineMatrix_transpose(theta1_t,self.theta1,rows,cols,line_remainder,block=(self.MAX_ThreadBlock_Width,self.MAX_ThreadBlock_Height,1),grid=(line_quotient,col_quotient))
		

		'''
		matrix_transpose(theta1_t,self.theta1,block=(self.theta1.shape[0],1,1),grid=(self.theta1.shape[1],1))
		'''
		line_quotient_1,line_remainder_1 = divmod(self.input_nodenum,self.MAX_ThreadBlock_Width)
		if line_remainder_1!=0:
			line_quotient_1 += 1
		line_remainder_1 = np.int32(line_remainder_1)
		col_quotient_1,col_remainder_1 = divmod(batchsize,self.MAX_ThreadBlock_Height)
		if col_remainder_1!=0:
			col_quotient_1 += 1


		BigCOLMatrix_mul(delta_x,-factor0,theta1_t,xh,xw,yw,line_remainder_1,block=(self.MAX_ThreadBlock_Width,self.MAX_ThreadBlock_Height,1),grid=(line_quotient_1,col_quotient_1))
		'''
		mat_mul(delta_x , -factor0 , theta1_t , xw_gpu , yw_gpu , block=(self.input_nodenum,1,1) , grid=(self.hid2_nodenum,1))
		'''

		delta_x_value = delta_x.get()	

		self.theta1 = self.theta1 + theta1_delta
		self.theta2 = self.theta2 + theta2_delta
		self.theta3 = self.theta3 + theta3_delta
	
		self.b1 = self.b1 + b1_delta
		self.b2 = self.b2 + b2_delta
		self.b3 = self.b3 + b3_delta

		
		vec_length = self.lookup_table.embedding_length
		for i in xrange(batchsize):
			group = list_group_batch[i]			
			feature = list_feature_batch[i]
			count = 0
			for groupid in group:
				featureid = feature[count]
				offset = self.lookup_table.groupid_offset[groupid]
				
				pos = self.lookup_table.QueryPos(groupid,featureid)
				self.lookup_table.central_array[pos:pos+vec_length] =  self.lookup_table.central_array[pos:pos+vec_length]  - self.alpha * delta_x_value[i][offset:offset+vec_length]

				count += 1
		
		trainx.gpudata.free()
		trainy.gpudata.free()
		hid1.gpudata.free()
		hid2.gpudata.free()
		out.gpudata.free()
		out_sum.gpudata.free()
		output.gpudata.free()
		
		output_t.gpudata.free()
		delta2.gpudata.free()
		theta3_delta.gpudata.free()
		delta_tmp.gpudata.free()
		b3_delta.gpudata.free()
		factor1.gpudata.free()
		theta3_t.gpudata.free()
		delta1.gpudata.free()
		factor1_t.gpudata.free()
		theta2_delta.gpudata.free()
		delta1_bias.gpudata.free()
		b2_delta.gpudata.free()
		factor0.gpudata.free()
		theta2_t.gpudata.free()
		delta0.gpudata.free()
		factor0_t.gpudata.free()
		delta0_bias.gpudata.free()
		b1_delta.gpudata.free()
		delta_x.gpudata.free()
		theta1_t.gpudata.free()
		

	def calc_auc(self,testx,testy,instancenum,list_feature_batch):
		return self.test_AUC(testx,testy,list_feature_batch)

