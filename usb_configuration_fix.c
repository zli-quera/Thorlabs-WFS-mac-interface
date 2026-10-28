#include <libusb.h>
#include <stdio.h>
static int target(libusb_device_handle *handle) {
    struct libusb_device_descriptor descriptor;
    return libusb_get_device_descriptor(libusb_get_device(handle),&descriptor)==0 &&
           descriptor.idVendor==0x1409 && descriptor.idProduct==0x3370;
}
static void prepare_link(libusb_device_handle *handle) {
    if(!target(handle))return;
    for(int feature=48;feature<=49;feature++) {
        int status=libusb_control_transfer(handle,0,LIBUSB_REQUEST_CLEAR_FEATURE,feature,0,NULL,0,1000);
        fprintf(stderr,"WFS clear USB3 link feature %d: %d\n",feature,status);
    }
}
static void prepare_endpoints(libusb_device_handle *handle) {
    if(!target(handle))return;
    prepare_link(handle);
    int output=libusb_clear_halt(handle,0x01);
    int input=libusb_clear_halt(handle,0x81);
    fprintf(stderr,"WFS endpoint recovery OUT=%d IN=%d\n",output,input);
}
static int wfs_open(libusb_device *dev,libusb_device_handle **handle) {
    int result=libusb_open(dev,handle);
    if(result==0 && target(*handle)) {
        int configuration=-1;
        if(libusb_get_configuration(*handle,&configuration)==0) {
            int status=libusb_set_configuration(*handle,1);
            fprintf(stderr,"WFS USB configuration %d -> 1: %d\n",configuration,status);
        }
        prepare_link(*handle);
    }
    return result;
}
static int wfs_claim(libusb_device_handle *handle,int interface) {
    int result=libusb_claim_interface(handle,interface);
    if(result==0 && interface==0)prepare_endpoints(handle);
    return result;
}
static int wfs_alt(libusb_device_handle *handle,int interface,int alternate) {
    int result=libusb_set_interface_alt_setting(handle,interface,alternate);
    if(result==0 && interface==0)prepare_endpoints(handle);
    return result;
}
static int wfs_reset(libusb_device_handle *handle) {
    if(target(handle)) {
        fprintf(stderr,"WFS preserving firmware state instead of redundant host reset\n");
        return 0;
    }
    return libusb_reset_device(handle);
}
#include "native/usb_trace.h"
__attribute__((used)) static struct {const void *replacement;const void *replacee;}
interposers[] __attribute__((section("__DATA,__interpose")))={
 {(const void*)wfs_open,(const void*)libusb_open},
 {(const void*)wfs_claim,(const void*)libusb_claim_interface},
 {(const void*)wfs_alt,(const void*)libusb_set_interface_alt_setting},
 {(const void*)wfs_submit,(const void*)libusb_submit_transfer},
 {(const void*)wfs_reset,(const void*)libusb_reset_device}
};
