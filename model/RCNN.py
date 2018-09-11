import tensorflow as tf
import numpy as np
import pandas as pd
word_embed_vector=np.load('../data/word_vec.npy')

class param(object):
    num_classes=19
    sequence_length=1000
    embed_size=100
    vocab_size=679250
    batch_size=128
    lr=5e-3
    epoch=10
    
class rnn_att_param(param):
    drop_keep_prob=0.5
    l2_lambda=1e-4
    hiddim=120
    hidden_size=128
    
arg=rnn_att_param()


class Basic_model:
    def __init__(self,num_classes,sequence_length,vocab_size,embed_size):
        self.num_classes = num_classes
        self.sequence_length = sequence_length
        self.vocab_size = vocab_size
        self.embed_size = embed_size
        self.global_steps=tf.Variable(0, trainable=False)
        self.embed=tf.Variable(word_embed_vector,name='embeding_vector')
        
        #placeholder
        self.x = tf.placeholder(tf.int32, [None, self.sequence_length], name="input_x1")  # X
        self.y = tf.placeholder(tf.float32,[None,19], name="labels")
        self.keep_prob=tf.placeholder(tf.float32,name="dropout_keep_prob")
        self.keep_prob_embed=tf.placeholder(tf.float32,name="keep_prob_embed")
        self.training=tf.placeholder(tf.bool,name="training")
        self.lr = tf.placeholder(tf.float32, name="learning_rate")
        self.lr_embed = tf.placeholder(tf.float32, name="embed_learning_rate")
        self.lamda=tf.placeholder(tf.float32, name="l2_regular")
        
        
    def weight_init(self,shape,name):
        with tf.variable_scope(name,reuse=tf.AUTO_REUSE):
            weight=tf.get_variable('kernel',shape,initializer=tf.contrib.layers.xavier_initializer())
        return  weight
    
    def bias_init(self,shape,name):
        with tf.variable_scope(name,reuse=tf.AUTO_REUSE):
            bias=tf.Variable(tf.zeros(shape)+0.1,tf.float32,name='bias')
        return  bias
    
    
#from tensorflow.contrib.cudnn_rnn.python.layers import cudnn_rnn
class RNN_att(Basic_model):
    def __init__(self,arg):
        super(RNN_att, self).__init__(arg.num_classes,arg.sequence_length,arg.vocab_size,arg.embed_size)
        self.hiddim=arg.hiddim
        self.hidden_size=arg.hidden_size
        self.char_svd=tf.placeholder(tf.float32,[None,200], name="char_svd")
        self.filter1=self.weight_init([1,self.hidden_size,1,256],name='filter1')
        self.bias1=self.bias_init([256],name='filter1')
        
        self.filter2=self.weight_init([2,self.hidden_size,1,256],name='filter2')
        self.bias2=self.bias_init([256],name='filter2')
        
        self.filter3=self.weight_init([3,self.hidden_size,1,256],name='filter3')
        self.bias3=self.bias_init([256],name='filter3')

        self.logit=self.forward()
        self.proba=tf.nn.softmax(self.logit,axis=1)  
        self.losses=tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits_v2(labels=self.y, logits=self.logit))
        self.l2_losses = tf.add_n([tf.nn.l2_loss(v) for v in tf.trainable_variables() if 'kernel' in v.name]) * self.lamda
        self.loss_add_reg=self.losses+self.l2_losses
        [print(v) for v in tf.trainable_variables() if 'kernel' in v.name]
        self.acc=tf.reduce_mean(tf.cast(tf.equal(tf.argmax(self.logit,1),tf.argmax(self.y,1)),tf.float32))

        var1 = [v for v in tf.trainable_variables() if 'embeding_vector' in v.name]
        var2 = [v for v in tf.trainable_variables() if 'embeding_vector' not in v.name]
        print ('pretrained,fine-tuning',var1[0])
        
        update_ops = tf.get_collection(tf.GraphKeys.UPDATE_OPS)
        with tf.control_dependencies(update_ops):
            self.train_step1=tf.train.AdamOptimizer(self.lr_embed).minimize(self.loss_add_reg,var_list=var1)
            self.train_step2=tf.train.AdamOptimizer(self.lr).minimize(self.loss_add_reg,global_step=self.global_steps,var_list=var2)
            self.train_op = tf.group(self.train_step1, self.train_step2)
      
    def conv(self,x,W,b):
        return tf.nn.conv2d(x,W,strides=[1,1,1,1],padding='VALID')+b
    
    def forward(self):
        
        s = tf.nn.embedding_lookup(self.embed,self.x)#[None,sentence_length,embed_size,1]
        print ('s',s.shape)
        
        s2=tf.transpose(s,[1,0,2])
        print (s2.shape)
        
        rnn = tf.contrib.cudnn_rnn.CudnnLSTM(num_layers=1, num_units=self.hidden_size//2, direction='bidirectional')
        rnn_out,_=rnn(s2)
        o1 = tf.transpose(rnn_out,[1,0,2])
        print ('o1.shape',o1.shape)

        o1b=tf.expand_dims(o1,-1)
        print ('o1b.shape',o1b.shape)
        
        
        o2a=tf.squeeze(tf.nn.relu((self.conv(o1b,self.filter1,self.bias1))),[2])
        o2b=tf.squeeze(tf.nn.relu((self.conv(o1b,self.filter2,self.bias2))),[2])
        o2c=tf.squeeze(tf.nn.relu((self.conv(o1b,self.filter3,self.bias3))),[2])
        
        print (o2a.shape,o2b.shape,o2c.shape)
                   
        o3a=tf.keras.layers.GlobalAveragePooling1D()(o2a)
        o3b=tf.keras.layers.GlobalAveragePooling1D()(o2b)
        o3c=tf.keras.layers.GlobalAveragePooling1D()(o2c)
        print (o3a.shape,o3b.shape,o3c.shape)
        
        #concat
        con=tf.concat([o3a,o3b,o3c,self.char_svd],axis=-1)
        condrop=tf.nn.dropout(con,self.keep_prob)
        print ('condrop',condrop.shape)
        
        hid=tf.layers.dense(condrop,self.hiddim,activation=None,use_bias=True,
                           kernel_initializer=tf.contrib.layers.xavier_initializer()
                           ,kernel_regularizer=None)
        hid2=tf.nn.dropout(tf.nn.relu(tf.layers.batch_normalization(hid,training=self.training)),self.keep_prob)
        print('hid2',hid2.shape)
        score=tf.layers.dense(hid2,self.num_classes,activation=None,use_bias=True,
                           kernel_initializer=tf.contrib.layers.xavier_initializer()
                           ,kernel_regularizer=None)
        
        print ('score',score.shape)
        return score   
    
    
tf.reset_default_graph()
ss=RNN_att(arg)


char_svd_train=np.load('../data/article_train_tfidf_svd.npy')
char_svd_test=np.load('../data/article_test_tfidf_svd.npy')

import sys
use_test=[]
cv_fold=int(sys.argv[1])
print (cv_fold)
if cv_fold==1:
    use_test=list(range(50001))
if cv_fold==2:
    use_test=list(range(50000,102277))
if cv_fold==3:
    use_test=list(range(30000,80001))
if cv_fold==4:
    use_test=list(range(30001))+list(range(80000,102277))
if cv_fold==5:
    use_test=list(range(12000))+list(range(24000,36000))+list(range(48000,60000))+list(range(72000,90000))
print (len(use_test),use_test[0],use_test[-1])


train_embed=np.load('../data/train_embed.npy')
test_embed=np.load('../data/test_embed.npy')[use_test]
labels=np.load('../data/labels.npy')
labels-=1
slabel=np.zeros((labels.shape[0],19))
slabel[np.arange(labels.shape[0]),labels]=1.0
np.random.seed(2018)

r1=(np.random.uniform(0,1,train_embed.shape[0])*5).astype(np.int32)
filter_t=(r1!=(cv_fold-1))
filter_v=~filter_t
x_train , y_train,svd_train = train_embed[filter_t],slabel[filter_t],char_svd_train[filter_t]
x_val  ,  y_val ,svd_val = train_embed[filter_v],slabel[filter_v],char_svd_train[filter_v]

test_pred_labels=np.load('../stacking/stacking.npy')[use_test]
svd_test=char_svd_test
presudo_svd=char_svd_test[use_test]


x_train=np.concatenate((x_train,test_embed),axis=0)
y_train=np.concatenate((y_train,test_pred_labels))
svd_train=np.concatenate((svd_train,presudo_svd))
print (x_train.shape,y_train.shape,svd_train.shape)

import random
import gc
r2=list(range(x_train.shape[0]))



saver = tf.train.Saver()
lastacc=0
lastloss=99999
learning_rate=1e-3
embed_rate=2e-4
finetune=False
with tf.Session() as sess:
    sess.run(tf.global_variables_initializer())
    for ep in range(50):
        ite=0
        random.shuffle(r2) 
        while(ite<x_train.shape[0]):
            gc.collect()
            global_step=sess.run(ss.global_steps)
            feed={ss.x:x_train[r2[ite:ite+arg.batch_size],:], 
                  ss.y:y_train[r2[ite:ite+arg.batch_size]],
                  ss.char_svd:svd_train[r2[ite:ite+arg.batch_size]],
                  ss.training:True,ss.lr:learning_rate,ss.lr_embed:embed_rate,ss.lamda:1e-4,
                  ss.keep_prob:arg.drop_keep_prob}
            ite+=arg.batch_size
            if finetune:
                sess.run([ss.train_op],feed_dict=feed)
            else:
                sess.run([ss.train_step2],feed_dict=feed)
            if (ite//arg.batch_size)%50==0:
                print (sess.run([ss.acc,ss.losses,ss.loss_add_reg,ss.global_steps],feed_dict=feed),learning_rate,finetune)

        ite=0
        mypred=[]
        myloss=0
        while(ite<x_val.shape[0]):
            gc.collect()
            feed={ss.x:x_val[ite:ite+arg.batch_size,:],
                  ss.y:y_val[ite:ite+arg.batch_size],
                  ss.char_svd:svd_val[ite:ite+arg.batch_size],
                    ss.training:False,
                    ss.keep_prob:1.0}
            pred,loss=sess.run([ss.logit,ss.losses],feed_dict=feed)
            mypred.extend(list(np.argmax(pred,1)+1))
            myloss+=loss*x_val[ite:ite+arg.batch_size,:].shape[0]
            ite+=arg.batch_size
        myloss/=x_val.shape[0]
        acc=np.mean(np.array(mypred)==(np.argmax(y_val,1)+1))
        print (acc,myloss)
        if myloss<lastloss:
            saver.save(sess,"../data/checkpoint/rcnn%d.ckpt"%cv_fold)
            if myloss<lastloss:
                lastloss=myloss
        else:
            if finetune:
                learning_rate/=1.25
                embed_rate/=1.25
            else:
                learning_rate/=2
                embed_rate/=2
            if learning_rate<2e-4:
                finetune=True 
            if learning_rate<6e-5:
                break

                
saver = tf.train.Saver()
import gc
with tf.Session() as sess:
    saver.restore(sess, "../data/checkpoint/rcnn%d.ckpt"%cv_fold)
    ite=0
    mypred=[]
    myloss=0
    x_val_proba=np.zeros((x_val.shape[0],19))
    while(ite<x_val.shape[0]):
        gc.collect()
        feed={ss.x:x_val[ite:ite+arg.batch_size,:],
              ss.y:y_val[ite:ite+arg.batch_size],
              ss.char_svd:svd_val[ite:ite+arg.batch_size],
                ss.training:False,
                ss.keep_prob:1.0}
        
        pred,loss,proba=sess.run([ss.logit,ss.losses,ss.proba],feed_dict=feed)
        mypred.extend(list(np.argmax(pred,1)+1))
        myloss+=loss*x_val[ite:ite+arg.batch_size,:].shape[0]
        x_val_proba[ite:ite+arg.batch_size,:]=np.array(proba)
        ite+=arg.batch_size        
    myloss/=x_val.shape[0]
    acc=np.mean(np.array(mypred)==np.argmax(y_val,1)+1)
    print (cv_fold,acc,myloss)
    np.save('../stacking/rcnn/val_rcnn_%d.npy'%cv_fold,x_val_proba)
    
test_embed=np.load('../data/test_embed.npy')
import gc
gc.collect()
print ("test")
saver = tf.train.Saver()
mypred=[]
with tf.Session() as sess:
    saver.restore(sess, "../data/checkpoint/rcnn%d.ckpt"%cv_fold)
    ite=0
    x_test_proba=np.zeros((test_embed.shape[0],19))
    while(ite<test_embed.shape[0]):
        gc.collect()
        feed={ss.x:test_embed[ite:ite+arg.batch_size,:],
                ss.training:False,
                  ss.char_svd:svd_test[ite:ite+arg.batch_size],
                ss.keep_prob:1.0}
        proba,logit=sess.run([ss.proba,ss.logit],feed_dict=feed)
        x_test_proba[ite:ite+arg.batch_size,:]=np.array(proba)
        mypred.extend(list(np.argmax(logit,1)+1))
        ite+=arg.batch_size
    np.save('../stacking/rcnn/test_rcnn_%d.npy'%cv_fold,x_test_proba)                
