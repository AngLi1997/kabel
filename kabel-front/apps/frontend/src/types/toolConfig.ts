import type { Attribute } from '@kabel/interface';

export interface ToolsConfigState {
  tools: any[];
  tagList: any[];
  attributes: Attribute[];
  textConfig: any;
  commonAttributeConfigurable: boolean;
}
