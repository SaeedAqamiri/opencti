/*
Copyright (c) 2021-2025 Filigran SAS

This file is part of the OpenCTI Enterprise Edition ("EE") and is
licensed under the OpenCTI Enterprise Edition License (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

https://github.com/OpenCTI-Platform/opencti/blob/master/LICENSE

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
*/

import type { Resolvers } from '../../generated/graphql';
import {
  changeTone,
  convertFilesToStix,
  explain,
  fixSpelling,
  generateContainerReport,
  generateNLQresponse,
  generateEntityReport,
  convertIndicator,
  improveWriting,
  makeLonger,
  makeShorter,
  summarize,
  summarizeFiles,
  translate,
} from './ai-domain';
import { BUS_TOPICS } from '../../config/conf';
import { AI_BUS } from './ai-types';
import { subscribeToAiEvents } from '../../graphql/subscriptionWrapper';

const aiResolvers: Resolvers = {
  Mutation: {
    aiContainerGenerateReport: (_, args, context) => generateContainerReport(context, context.user, args),
    aiSummarizeFiles: (_, args, context) => summarizeFiles(context, context.user, args),
    aiConvertFilesToStix: (_, args, context) => convertFilesToStix(context, context.user, args),
    aiFixSpelling: (_, { id, content, format }, context) => fixSpelling(context, context.user, id, content, format),
    aiMakeShorter: (_, { id, content, format }, context) => makeShorter(context, context.user, id, content, format),
    aiMakeLonger: (_, { id, content, format }, context) => makeLonger(context, context.user, id, content, format),
    aiChangeTone: (_, { id, content, format, tone }, context) => changeTone(context, context.user, id, content, format, tone),
    aiSummarize: (_, { id, content, format }, context) => summarize(context, context.user, id, content, format),
    aiExplain: (_, { id, content }, context) => explain(context, context.user, id, content),
    aiImproveWriting: (_, { id, content, format }, context) => improveWriting(context, context.user, id, content, format),
    aiThreatGenerateReport: (_, { id, threatId, paragraphs, tone, format }, context) => generateEntityReport(context, context.user, id, threatId, paragraphs ?? undefined, tone ?? undefined, format ?? undefined),
    aiVictimGenerateReport: (_, { id, victimId, paragraphs, tone, format }, context) => generateEntityReport(context, context.user, id, victimId, paragraphs ?? undefined, tone ?? undefined, format ?? undefined),
    aiConvertIndicator: (_, { id, indicatorId, format }, context) => convertIndicator(context, context.user, id, indicatorId, format),
    aiTranslate: (_, { id, content, format, language }, context) => translate(context, context.user, id, content, format, language),
    aiNLQ: (_, args, context) => generateNLQresponse(context, context.user, args),
  },
  Subscription: {
    aiBus: {
      resolve: /* v8 ignore next */ (payload: any) => payload.instance,
      subscribe: /* v8 ignore next */ (_, { id }, context) => {
        const bus = BUS_TOPICS[AI_BUS];
        return subscribeToAiEvents(context, id, [bus.EDIT_TOPIC]);
      },
    },
  },
};

export default aiResolvers;
