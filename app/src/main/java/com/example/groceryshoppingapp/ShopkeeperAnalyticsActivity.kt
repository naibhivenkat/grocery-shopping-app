package com.example.groceryshoppingapp

import android.os.Bundle
import android.util.Log
import android.view.View
import android.widget.ProgressBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.example.groceryshoppingapp.adapters.ShopReviewsAdapter
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.network.ShopRatingAnalyticsResponse
import com.example.groceryshoppingapp.network.ShopReviewsResponse
import com.example.groceryshoppingapp.utils.SessionManager
import com.google.android.material.bottomsheet.BottomSheetBehavior
import com.google.android.material.bottomsheet.BottomSheetDialog
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response

class ShopkeeperAnalyticsActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_shopkeeper_analytics)

        val shopId = SessionManager.getShopId(this) ?: return
        fetchAnalytics(shopId)
    }

    // --------------------------------------------------
    // 🔹 Fetch Analytics
    // --------------------------------------------------
    private fun fetchAnalytics(shopId: String) {

        val api = RetrofitClient
            .getInstance(this)
            .create(ApiService::class.java)

        api.getShopRatingAnalytics(shopId)
            .enqueue(object : Callback<ShopRatingAnalyticsResponse> {

                override fun onResponse(
                    call: Call<ShopRatingAnalyticsResponse>,
                    response: Response<ShopRatingAnalyticsResponse>
                ) {
                    if (response.isSuccessful && response.body() != null) {
                        bindUI(response.body()!!)
                    }
                }

                override fun onFailure(call: Call<ShopRatingAnalyticsResponse>, t: Throwable) {
                    Log.e("ANALYTICS", "Failed to load analytics", t)
                }
            })
    }

    // --------------------------------------------------
    // 🔹 Bind Main Analytics UI
    // --------------------------------------------------
    private fun bindUI(data: ShopRatingAnalyticsResponse) {

        findViewById<TextView>(R.id.txtAvgRating).text =
            "⭐ ${data.average_rating}"

        findViewById<TextView>(R.id.txtTotalRatings).text =
            "${data.total_ratings} ratings"

        bindEmojiRow(
            rowId = R.id.row_love,
            emoji = "😍",
            rating = 5,
            count = data.emoji_breakdown["😍"] ?: 0,
            total = data.total_ratings
        )

        bindEmojiRow(
            rowId = R.id.row_good,
            emoji = "🙂",
            rating = 4,
            count = data.emoji_breakdown["🙂"] ?: 0,
            total = data.total_ratings
        )

        bindEmojiRow(
            rowId = R.id.row_okay,
            emoji = "😐",
            rating = 3,
            count = data.emoji_breakdown["😐"] ?: 0,
            total = data.total_ratings
        )

        bindEmojiRow(
            rowId = R.id.row_bad,
            emoji = "😡",
            rating = 1,
            count = data.emoji_breakdown["😡"] ?: 0,
            total = data.total_ratings
        )
    }

    // --------------------------------------------------
    // 🔹 Bind Each Emoji Row (CLICKABLE)
    // --------------------------------------------------
    private fun bindEmojiRow(
        rowId: Int,
        emoji: String,
        rating: Int,
        count: Int,
        total: Int
    ) {
        val row = findViewById<View>(rowId)

        val txtEmoji = row.findViewById<TextView>(R.id.txtEmoji)
        val txtCount = row.findViewById<TextView>(R.id.txtEmojiCount)
        val progress = row.findViewById<ProgressBar>(R.id.progressEmoji)

        txtEmoji.text = emoji
        txtCount.text = count.toString()

        progress.max = if (total == 0) 1 else total
        progress.progress = count

        // ⭐ CLICK → SHOW REVIEWS
        row.setOnClickListener {
            showReviewsBottomSheet(rating)
        }
    }

    // --------------------------------------------------
    // ⭐ Reviews Bottom Sheet (FILTER BY RATING)
    // --------------------------------------------------
    private fun showReviewsBottomSheet(rating: Int) {

        val dialog = BottomSheetDialog(this)
        val view = layoutInflater.inflate(R.layout.bottom_sheet_reviews, null)
        dialog.setContentView(view)

        dialog.behavior.peekHeight = resources.displayMetrics.heightPixels
        dialog.behavior.state = BottomSheetBehavior.STATE_EXPANDED

        val recycler = view.findViewById<RecyclerView>(R.id.recyclerReviews)
        val txtEmpty = view.findViewById<TextView>(R.id.txtEmpty)

        recycler.layoutManager = LinearLayoutManager(this)

        val api = RetrofitClient.getInstance(this).create(ApiService::class.java)
        val shopId = SessionManager.getShopId(this) ?: return

        api.getShopReviewsByRating(shopId, rating)
            .enqueue(object : Callback<ShopReviewsResponse> {

                override fun onResponse(
                    call: Call<ShopReviewsResponse>,
                    response: Response<ShopReviewsResponse>
                ) {
                    val reviews = response.body()?.reviews ?: emptyList()

                    Log.d("REVIEWS_API", "rating=$rating → ${reviews.size} reviews")

                    if (reviews.isEmpty()) {
                        txtEmpty.visibility = View.VISIBLE
                        recycler.visibility = View.GONE
                    } else {
                        txtEmpty.visibility = View.GONE
                        recycler.visibility = View.VISIBLE
                        recycler.adapter = ShopReviewsAdapter(reviews)
                    }
                }

                override fun onFailure(call: Call<ShopReviewsResponse>, t: Throwable) {
                    Log.e("REVIEWS", "Failed to load reviews", t)
                    txtEmpty.visibility = View.VISIBLE
                }
            })

        dialog.show()
    }
}
