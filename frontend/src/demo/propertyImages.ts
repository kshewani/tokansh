export type PropertyImageInput={symbol?:string|null;name?:string|null;propertyId?:string|null};

const images:Record<string,string>={
 'ANSH-OAK':'/images/properties/silver-oak.webp',
 'ANSH-GREEN':'/images/properties/green-acres.webp',
 'ANSH-NEST':'/images/properties/urban-nest.webp',
 'ANSH-CORNER':'/images/properties/cornerstone.webp',
 'ANSH-HILL':'/images/properties/hillcrest.webp',
 'ANSH-METRO':'/images/properties/metro-logistics.webp',
 'ANSH-PALM':'/images/properties/palm-haven.webp',
 'ANSH-SUMMIT':'/images/properties/summit.webp'
};

export const PROPERTY_IMAGE_FALLBACK='/images/properties/property-fallback.svg';

function key(value:string|null|undefined){return typeof value==='string'?value.trim().toUpperCase():'';}

/** Presentation-only image lookup. Canonical property identity remains the full UUID. */
export function propertyImageFor({symbol,name}:PropertyImageInput):string{
 const symbolKey=key(symbol);
 if(images[symbolKey])return images[symbolKey];
 const nameKey=key(name);
 const match=Object.keys(images).find(value=>nameKey.includes(value.replace('ANSH-','')));
 return match?images[match]:PROPERTY_IMAGE_FALLBACK;
}

export function showcaseImageEntries(){return Object.entries(images).map(([symbol,src])=>({symbol,src}));}
