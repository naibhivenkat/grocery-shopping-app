package com.example.groceryshoppingapp

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.Log
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.RatingBar
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.airbnb.lottie.LottieAnimationView
import com.example.groceryshoppingapp.databinding.ActivityThankYouBinding
import com.example.groceryshoppingapp.network.ApiService
import com.example.groceryshoppingapp.network.RetrofitClient
import com.example.groceryshoppingapp.util.CartManager
import com.example.groceryshoppingapp.utils.SessionManager
import com.google.android.material.bottomsheet.BottomSheetDialog

import com.example.groceryshoppingapp.network.ApiResponse
import com.example.groceryshoppingapp.network.ShopRatingRequest


class ThankYouActivity : AppCompatActivity() {

    private lateinit var binding: ActivityThankYouBinding

    private var customerId: String? = null
    private var shopId: String = ""
    private var orderId: String = ""

    // lifecycle-safe handler
    private val handler = Handler(Looper.getMainLooper())
    private var ratingRunnable: Runnable? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityThankYouBinding.inflate(layoutInflater)
        setContentView(binding.root)

        customerId = SessionManager.getCustomerId(this)
        val customerName = SessionManager.getUsername(this) ?: "Customer"

        shopId = intent.getStringExtra("shop_id") ?: ""
        orderId = intent.getStringExtra("order_id") ?: ""

        Log.d("THANK_YOU", "customerId=$customerId shopId=$shopId orderId=$orderId")

        binding.textViewThankYou.text = "Thank you, $customerName!"
        binding.textViewSubMessage.text = "Your order has been successfully placed 🎉"

        CartManager.clearAllCarts()

        findViewById<LottieAnimationView>(R.id.successAnimation).playAnimation()

        ratingRunnable = Runnable {
            if (!isFinishing && !isDestroyed) {
                showRatingBottomSheet()
            }
        }
        handler.postDelayed(ratingRunnable!!, 1200)

        binding.buttonBackToHome.setOnClickListener {
            goToHome()
        }
    }

    // ==================================================
    // ⭐ Emoji Rating Bottom Sheet
    // ==================================================
    private fun showRatingBottomSheet() {

        if (isFinishing || isDestroyed) return
        if (shopId.isBlank()) return
        if (orderId.isNotBlank() && SessionManager.isOrderRated(this, orderId)) return

        val dialog = BottomSheetDialog(this)
        val view = layoutInflater.inflate(R.layout.bottom_sheet_rate_shop, null)
        dialog.setContentView(view)
        dialog.setCancelable(false)

        val ratingBar = view.findViewById<RatingBar>(R.id.ratingBar)
        val reviewEdit = view.findViewById<EditText>(R.id.editReview)
        val btnSubmit = view.findViewById<Button>(R.id.btnSubmitRating)
        val btnSkip = view.findViewById<TextView>(R.id.btnSkip)

        val emojiBad = view.findViewById<TextView>(R.id.emojiBad)
        val emojiOkay = view.findViewById<TextView>(R.id.emojiOkay)
        val emojiGood = view.findViewById<TextView>(R.id.emojiGood)
        val emojiLove = view.findViewById<TextView>(R.id.emojiLove)
        val emojiLabel = view.findViewById<TextView>(R.id.textEmojiLabel)

        fun selectEmoji(rating: Float, selected: TextView, label: String) {
            ratingBar.rating = rating

            listOf(emojiBad, emojiOkay, emojiGood, emojiLove).forEach {
                it.alpha = if (it == selected) 1f else 0.4f
                it.scaleX = if (it == selected) 1.2f else 1f
                it.scaleY = if (it == selected) 1.2f else 1f
            }

            emojiLabel.text = label
            emojiLabel.visibility = View.VISIBLE
        }

        emojiBad.setOnClickListener {
            selectEmoji(1f, emojiBad, "Bad")
        }

        emojiOkay.setOnClickListener {
            selectEmoji(3f, emojiOkay, "Average")
        }

        emojiGood.setOnClickListener {
            selectEmoji(4f, emojiGood, "Good")
        }

        emojiLove.setOnClickListener {
            selectEmoji(5f, emojiLove, "Excellent")
        }

        btnSubmit.setOnClickListener {

            val rating = ratingBar.rating
            val review = reviewEdit.text.toString().trim()

            if (rating == 0f) {
                reviewEdit.error = "Please select a reaction 😄"
                return@setOnClickListener
            }

            submitShopRating(rating, review)
            SessionManager.markOrderRated(this, orderId)
            dialog.dismiss()
        }

        btnSkip.setOnClickListener {
            dialog.dismiss()
        }

        dialog.show()
    }

    private fun submitShopRating(rating: Float, review: String) {

        val emoji = when (rating.toInt()) {
            1 -> "😡"
            3 -> "😐"
            4 -> "🙂"
            5 -> "😍"
            else -> ""
        }

        val request = customerId?.let {
            ShopRatingRequest(
                order_id = orderId,
                shop_id = shopId,
                customer_id = it,
                customer_name = SessionManager.getUsername(this) ?: "Customer",
                rating = rating,
                review = review,
                emoji = emoji
            )
        }

        val api = RetrofitClient
            .getInstance(this)
            .create(ApiService::class.java)

        if (request != null) {
            api.rateShop(request).enqueue(object : retrofit2.Callback<ApiResponse> {

                override fun onResponse(
                    call: retrofit2.Call<ApiResponse>,
                    response: retrofit2.Response<ApiResponse>
                ) {
                    if (response.isSuccessful && response.body()?.success == true) {
                        Log.d("SHOP_RATING", "Rating submitted successfully")
                    } else {
                        Log.e(
                            "SHOP_RATING",
                            "Failed: ${response.body()?.message ?: response.code()}"
                        )
                    }
                }

                override fun onFailure(
                    call: retrofit2.Call<ApiResponse>,
                    t: Throwable
                ) {
                    Log.e("SHOP_RATING", "Error submitting rating", t)
                }
            })
        }
    }



    private fun goToHome() {
        val intent = Intent(this, CustomerHomeActivity::class.java)
        intent.flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TASK
        startActivity(intent)
    }

    override fun onDestroy() {
        super.onDestroy()
        ratingRunnable?.let { handler.removeCallbacks(it) }
    }
}
