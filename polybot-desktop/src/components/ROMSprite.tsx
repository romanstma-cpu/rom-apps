import type { CSSProperties } from 'react';
import logo from '../assets/rom-logo.svg';
export function ROMSprite({size=48,className='',style,title}: {size?:number;pet?:boolean;className?:string;style?:CSSProperties;title?:string}) {
 return <img src={logo} alt="ROM" title={title || 'ROM Polybot'} className={`inline-block shrink-0 ${className}`} style={{width:size,height:size,...style}} />;
}
