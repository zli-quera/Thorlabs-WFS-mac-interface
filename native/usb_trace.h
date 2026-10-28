#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
struct trace_pending { struct libusb_transfer *transfer; libusb_transfer_cb_fn callback; uint64_t id; struct trace_pending *next; };
static pthread_mutex_t trace_mutex=PTHREAD_MUTEX_INITIALIZER;
static struct trace_pending *trace_head;
static uint64_t trace_sequence=0, trace_total=0;
static void trace_record(struct libusb_transfer *t,int event,uint64_t id) {
 const char *path=getenv("WFS_NATIVE_TRACE");if(!path)return;
 uint32_t size=event ? (t->actual_length>0 ? t->actual_length:0): ((!(t->endpoint&0x80)||t->type==0)?t->length:0);
 if(event && t->type==0)size+=8;
 if(size>(uint32_t)t->length)size=t->length;
 if(trace_total>20000000)return;
 FILE*f=fopen(path,"ab");if(!f)return;
 struct timespec ts;clock_gettime(CLOCK_MONOTONIC,&ts);
 uint64_t ns=(uint64_t)ts.tv_sec*1000000000+ts.tv_nsec;
 uint32_t header[10]={0x32534657,event,(uint32_t)id,t->endpoint,t->type,event?(uint32_t)t->status:0,(uint32_t)t->length,size,(uint32_t)ns,(uint32_t)(ns>>32)};
 fwrite(header,4,10,f);if(size)fwrite(t->buffer,1,size,f);fclose(f);trace_total+=40+size;
}
static void LIBUSB_CALL trace_complete(struct libusb_transfer*t) {
 pthread_mutex_lock(&trace_mutex);
 struct trace_pending **cursor=&trace_head,*item=NULL;
 while(*cursor){if((*cursor)->transfer==t){item=*cursor;*cursor=item->next;break;}cursor=&(*cursor)->next;}
 if(!item){pthread_mutex_unlock(&trace_mutex);return;}
 t->callback=item->callback;trace_record(t,1,item->id);
 libusb_transfer_cb_fn callback=item->callback;free(item);
 pthread_mutex_unlock(&trace_mutex);
 if(callback)callback(t);
}
static int wfs_submit(struct libusb_transfer*t) {
 if(!getenv("WFS_NATIVE_TRACE"))return libusb_submit_transfer(t);
 struct trace_pending*item=malloc(sizeof(*item));if(!item)return LIBUSB_ERROR_NO_MEM;
 pthread_mutex_lock(&trace_mutex);
 item->transfer=t;item->callback=t->callback;item->id=++trace_sequence;item->next=trace_head;trace_head=item;
 trace_record(t,0,item->id);t->callback=trace_complete;
 pthread_mutex_unlock(&trace_mutex);
 int r=libusb_submit_transfer(t);
 if(r){pthread_mutex_lock(&trace_mutex);struct trace_pending**p=&trace_head;while(*p&&*p!=item)p=&(*p)->next;if(*p)*p=item->next;t->callback=item->callback;free(item);pthread_mutex_unlock(&trace_mutex);}
 return r;
}
