package com.gazeqa.generated;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

@DisplayName("Generated story lifecycle alignment")
class StoryLifecycleTest {
  private static final Path RUN_ROOT = Path.of(".").toAbsolutePath().normalize();
  private static final Path STORIES_JSON = RUN_ROOT.resolve("../../frd/stories_export.json").normalize();

  private List<Map<String, Object>> loadStories() throws IOException {
    ObjectMapper mapper = new ObjectMapper();
    Map<String, Object> payload = mapper.readValue(
        Files.newBufferedReader(STORIES_JSON), new TypeReference<>() {});
    Object features = payload.get("features");
    if (!(features instanceof List<?> list)) {
      throw new IllegalStateException("features list missing");
    }
    @SuppressWarnings("unchecked")
    List<Map<String, Object>> typed = (List<Map<String, Object>>) list;
    return typed;
  }

  @Test
  @DisplayName("STORY-FR-006-DASHBOARD flow is exported")
  void dashboardStoryPresent() throws IOException {
    List<Map<String, Object>> stories = loadStories();
    boolean found = stories.stream()
        .anyMatch(item -> "STORY-FR-006-DASHBOARD".equals(item.get("story_id")));
    assertTrue(found, "Dashboard story must exist in export");
  }

  @Test
  @DisplayName("Scenario export preserves acceptance criteria counts")
  void acceptanceCriteriaCounts() throws IOException {
    List<Map<String, Object>> stories = loadStories();
    Map<String, Long> counts = stories.stream()
        .collect(Collectors.toMap(
            item -> (String) item.get("story_id"),
            item -> {
              Object criteria = item.get("acceptance_criteria");
              if (criteria instanceof List<?> list) {
                return (long) list.size();
              }
              return 0L;
            }));
    assertEquals(2L, counts.get("STORY-FR-006-DASHBOARD"));
    assertEquals(2L, counts.get("STORY-FR-006-LOGIN"));
    assertEquals(2L, counts.get("STORY-FR-006-SCENARIO-AUTHORING"));
  }
}
