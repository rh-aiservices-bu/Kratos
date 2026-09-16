import { useState } from 'react';
import { Page, PageSection, Tab, Tabs, TabTitleText } from '@patternfly/react-core';
import { AccessControlTab } from './AccessControlTab';
import { ModelsTab } from './ModelsTab';
import { SubscriptionsTab } from './SubscriptionsTab';

type TabKey = 'subscriptions' | 'models' | 'access';

export function MaasOverviewPage() {
  const [activeTab, setActiveTab] = useState<TabKey>('subscriptions');

  return (
    <Page>
      <PageSection>
        <p className="kratos-section-heading">MaaS Setup</p>
        <Tabs
          activeKey={activeTab}
          onSelect={(_evt, key) => setActiveTab(key as TabKey)}
          aria-label="MaaS setup sections"
        >
          <Tab eventKey="subscriptions" title={<TabTitleText>Subscriptions</TabTitleText>}>
            <div style={{ marginTop: '1rem' }}>
              <SubscriptionsTab />
            </div>
          </Tab>
          <Tab eventKey="models" title={<TabTitleText>Models</TabTitleText>}>
            <div style={{ marginTop: '1rem' }}>
              <ModelsTab />
            </div>
          </Tab>
          <Tab eventKey="access" title={<TabTitleText>Access Control</TabTitleText>}>
            <div style={{ marginTop: '1rem' }}>
              <AccessControlTab />
            </div>
          </Tab>
        </Tabs>
      </PageSection>
    </Page>
  );
}
