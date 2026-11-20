import {apiConfiguration,createRequest} from './client';
export {RequestError} from './client';
const config=apiConfiguration(import.meta.env||{});
export const API_MODE=config.mode;
export const API_BASE_URL=config.baseUrl;
export const realBackendConfigured=config.configured;
/** All DRUNIX operations must go through separately maintained Python APIs. */
export const request=createRequest(config);
export const idempotency=()=>crypto.randomUUID();
