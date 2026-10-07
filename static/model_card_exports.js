export function resultExportRequest(value,format){
 if(!['csv','json'].includes(format))throw Error('导出格式不可用');
 const id=value?.card?.id,receipt=value?.reading?.receipt;
 if(typeof id!=='string'||!/^[0-9a-f-]{36}$/.test(id)||typeof receipt!=='string'||!receipt)throw Error('请先运行口径卡');
 return {url:'/api/model-cards/'+id+'/result-export?'+new URLSearchParams({receipt,format}),filename:'model-card-current-result-'+id+'.'+format,mime:format==='csv'?'text/csv':'application/json'};
}
export async function downloadCurrentResult(value,format,isCurrent,io={fetch:globalThis.fetch,document:globalThis.document,URL:globalThis.URL}){
 const request=resultExportRequest(value,format);if(!isCurrent())return false;
 const response=await io.fetch(request.url,{credentials:'same-origin',cache:'no-store'});
 if(!response.ok){let message='结果暂不能导出，请重新运行';try{message=(await response.json()).error||message}catch{}throw Error(message);}
 if(!response.headers.get('Content-Type')?.startsWith(request.mime)||!response.headers.get('Content-Disposition')?.startsWith('attachment;'))throw Error('返回内容不是结果文件，请重新运行');
 const blob=await response.blob();if(!isCurrent())return false;
 const url=io.URL.createObjectURL(blob),link=io.document.createElement('a');
 try{link.href=url;link.download=request.filename;io.document.body.appendChild(link);link.click();return true;}
 finally{link.remove();(io.setTimeout||globalThis.setTimeout)(()=>io.URL.revokeObjectURL(url),1000);}
}
